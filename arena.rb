# frozen_string_literal: true
require_relative 'engine_boot'
require_relative 'p1846/board'
require_relative 'p1846/policy'
require_relative 'p1846/model'
require 'net/http'

module Arena1846
  VERSION = '1.0.0'
  STYLES = %w[balanced growth income random lmstudio].freeze

  # The upstream Ruby path walker validates individual routes. Search combinations
  # here because the site's combination optimizer is JavaScript, not native Ruby.
  def self.routes(game, entity)
    P1846.best_routes(game, entity)
  end

  class Bot
    attr_reader :game, :config
    def initialize(config)
      @config = config
      @seed = Integer(config.fetch('seed', 42))
      @names = (1..Integer(config.fetch('players', 3))).to_h { |i| [i.to_s, "AI #{i}"] }
      @styles = config.fetch('strategies', %w[balanced growth income])
      @net_weight = config.fetch('net_weight', 40.0).to_f
      @net = P1846::NeuralClient.new(config['net_url']) if config['net_url']
      @net_error = nil
      @net_used = false
      @game = fresh([])
    end

    def fresh(actions)
      Engine::Game::G1846::Game.new(@names, id: "1846#{@seed}", seed: @seed, actions: actions).maybe_raise!
    end

    def style(entity)
      player = entity.player? ? entity : entity.player
      @styles[(@names.keys.index(player&.id) || 0) % @styles.size]
    end

    def add(list, action, score, reason, cost: nil, revenue: nil, info: nil)
      list << { action: action.to_h, score: score, reason: reason, cost: cost, revenue: revenue, info: info || {} }
    end

    def candidates
      g = @game
      step = g.round.active_step
      e = step.current_entity
      types = step.actions(e)
      # Assign / SpecialTrack steps act for a company the player controls.
      if types.empty? && e
        pool = [e] + (e.player? ? e.companies : []) + g.minors.select { |m| m.owner == e }
        alt = pool.find { |candidate| !step.actions(candidate).empty? }
        if alt
          e = alt
          types = step.actions(e)
        end
      end
      if e.corporation? && types.include?('buy_train') && step.must_buy_train?(e)
        types += g.round.actions_for(e).select { |type| type == 'bankrupt' }
      end
      list = []
      s = style(e)
      rng = Random.new(@seed * 100_003 + g.current_action_id)
      if types.include?('bid')
        step.available.each do |company|
          cost = company.min_bid
          remaining = e.cash - step.committed_cash(e, true) - cost
          next if remaining < 0
          score = step.blank?(company) ? 2 : company.revenue.to_f * 3 + cost * 0.12
          score -= 100 if remaining < 120 && !step.blank?(company)
          add(list, Engine::Action::Bid.new(e, company: company, price: cost), score, '选择私营公司，保留开办铁路的资金',
              cost: cost, info: { company: company.id, blank: step.blank?(company) })
        end
      end
      if types.include?('par')
        owned = g.corporations.count { |c| c.owner == e }
        g.corporations.each do |corp|
          next unless g.can_par?(corp, e)
          next unless owned.zero? || e.cash > 500
          step.get_par_prices(e, corp).each do |price|
            next unless e.cash >= price.price * 2
            target = [e.cash / 3, 100].min
            score = 80 - (target - price.price).abs * 0.3 + rng.rand * 6
            score -= 20 if price.price < 80
            add(list, Engine::Action::Par.new(e, corporation: corp, share_price: price), score, '开办铁路，平衡股价与公司启动金',
                cost: price.price * 2, info: { corp: corp.id, par: price.price })
          end
        end
      end
      if types.include?('buy_shares') && e.player?
        g.corporations.select(&:ipoed).each do |corp|
          (corp.ipo_shares + g.share_pool.shares_of(corp)).each do |share|
            next if share.president && !corp.receivership?
            next unless step.can_buy?(e, share.to_bundle)
            own = corp.owner == e
            score = 30 + (own ? 12 : 0) + (corp.trains.any? ? 5 : 0) + rng.rand * 3
            score -= 20 if e.cash < share.price + 40
            add(list, Engine::Action::BuyShares.new(e, shares: [share]), score, own ? '向自己经营的铁路投入资本' : '投资已开办铁路',
                cost: share.price, info: { corp: corp.id, percent: share.percent })
          end
        end
      end
      if types.include?('sell_shares')
        bundles = if e.corporation?
                    step.issuable_shares(e)
                  else
                    g.corporations.flat_map { |c| g.bundles_for_corporation(e, c) }.select { |b| step.can_sell?(e, b) }
                  end
        bundles.each do |bundle|
          score = types.include?('pass') ? -20 : 100 + bundle.price * 0.01
          score = 60 if e.corporation?
          add(list, Engine::Action::SellShares.new(e, shares: bundle.shares, percent: bundle.percent, share_price: bundle.share_price),
              score, '按规则出售股份筹集资金', revenue: bundle.price, info: { corp: bundle.corporation.id, issue: e.corporation? })
        end
      end
      if types.include?('lay_tile')
        g.hexes.each do |hex|
          next unless step.tracker_available_hex(e, hex)
          step.upgradeable_tiles(e, hex).each do |tile|
            # Guard against degenerate "lay the same tile" candidates (A->A).
            next if tile.name == hex.tile.name || tile.color == hex.tile.color

            cost = P1846.tile_cost(g, e, hex, tile)
            next if g.track_buying_power(e) < cost
            tile.legal_rotations.each do |rotation|
              tile.rotate!(rotation)
              add(list, Engine::Action::LayTile.new(e, hex: hex, tile: tile, rotation: rotation),
                  P1846::Policy.score_lay_tile(g, e, { cost: cost, info: { hex: hex.id, tile: tile.name, upgrade: hex.tile.color != :white } }),
                  '拓展连通线路或升级城市', cost: cost,
                  info: { hex: hex.id, tile: tile.name, upgrade: hex.tile.color != :white })
            end
          end
        end
      end
      if types.include?('place_token')
        g.token_graph_for_entity(e).connected_nodes(e).keys.select(&:city?).each do |city|
          next unless city.tokenable?(e, free: false)
          score = e.cash > 250 ? 50 : -10
          add(list, Engine::Action::PlaceToken.new(e, city: city), score + rng.rand * 5, '在可达城市设置车站',
              cost: 80, info: { hex: city.hex.id, city: city.index })
        end
      end
      if types.include?('run_routes')
        routes, timed_out = Arena1846.routes(g, e)
        add(list, Engine::Action::RunRoutes.new(e, routes: routes), 100, timed_out ? '搜索预算内选择合法营运线路（未穷尽）' : '搜索合法线路及列车组合，选择较高收入',
            revenue: routes.sum { |r| (r.revenue rescue 0) }, info: { routes: routes.size })
      end
      if types.include?('dividend')
        target = s == 'income' ? 120 : (s == 'growth' ? 650 : 420)
        kind = if e.minor?
                 'half'
               elsif e.cash < target && g.phase.name != 'IV'
                 s == 'growth' ? 'withhold' : 'half'
               else
                 'payout'
               end
        step.dividend_types.each do |k|
          add(list, Engine::Action::Dividend.new(e, kind: k.to_s), k.to_s == kind ? 100 : 0, "#{s} 策略：根据公司储备选择分红方式",
              info: { kind: k.to_s })
        end
      end
      if types.include?('discard_train')
        e.trains.each do |train|
          add(list, Engine::Action::DiscardTrain.new(e, train: train), 100 - train.price * 0.01, '遵守持车上限，优先淘汰旧车',
              info: { train: train.name })
        end
      end
      if types.include?('buy_train')
        step.buyable_trains(e).select(&:from_depot?).each do |train|
          step.buyable_train_variants(train, e).each do |variant|
            price = variant[:price]
            cash = e.cash
            cash += e.owner.cash if e.corporation? && step.respond_to?(:president_may_contribute?) && step.president_may_contribute?(e)
            next if price > cash
            score = if e.trains.empty?
                      120
                    elsif e.trains.size < 2
                      70
                    elsif price >= 160 && e.cash >= price + 120 && g.phase.name != 'IV'
                      35
                    else
                      -10
                    end
            score -= price * 0.001
            add(list, Engine::Action::BuyTrain.new(e, train: train, price: price, variant: variant[:name]), score,
                '购买列车以形成营运能力并推进时代', cost: price, info: { train: train.name, variant: variant[:name], distance: train.distance })
          end
        end
      end
      # Company purchases are non-blocking before track; take only our own assets.
      if types.include?('buy_company') && e.corporation?
        g.purchasable_companies(e).each do |company|
          next unless company.owner == e.owner && e.cash >= company.min_price
          next if g.minor_by_id(company.id) && e.trains.size >= g.train_limit(e)
          add(list, Engine::Action::BuyCompany.new(e, company: company, price: company.min_price), 5, '收购总裁持有的私营公司',
              cost: company.min_price, info: { company: company.id })
        end
      end
      if e.corporation? && types.include?('bankrupt') && g.can_go_bankrupt?(e.owner, e)
        add(list, Engine::Action::Bankrupt.new(e), 200, '规则引擎判定无法履行购车义务', info: {})
      end
      add(list, Engine::Action::Pass.new(e), 0, '结束当前步骤', info: {}) if types.include?('pass')
      if list.empty?
        # A corporation may need its president to sell shares during an EMR.
        if e.corporation? && (p = e.owner)&.player? && g.round.actions_for(p).include?('sell_shares')
          ps = g.round.step_for(p, 'sell_shares')
          g.corporations.flat_map { |c| g.bundles_for_corporation(p, c) }.each do |b|
            next unless ps.can_sell?(p, b)
            add(list, Engine::Action::SellShares.new(p, shares: b.shares, percent: b.percent), 100 + b.price * 0.001,
                '总裁出售股份履行紧急购车义务', revenue: b.price, info: { corp: b.corporation.id })
          end
        end
      end
      list.each { |c| c[:score] = rng.rand * 100 if s == 'random' && c[:action]['type'] != 'pass' }
      list = list.sort_by { |c| -c[:score] }.uniq { |c| c[:action] }
      apply_net(list, e) if @net && list.size > 1 && style(e) == 'neural'
      list
    end

    def apply_net(list, entity)
      begin
        state = P1846.state_features(@game, entity)
        actions = list.map { |c| P1846.action_features(@game, c, entity) }
        scores = @net.scores(state, actions)
        list.each_with_index do |candidate, i|
          candidate[:net] = scores[i].to_f
          candidate[:prior] = candidate[:score]
          candidate[:score] += scores[i].to_f * @net_weight
        end
        list.sort_by! { |c| -c[:score] }
        @net_used = true
        @net_error = nil
      rescue StandardError => error
        @net_used = false
        @net_error = error.message
      end
    end

    # Execute one specific candidate; any engine rejection rolls the game back
    # to the accepted action list so the state stays exactly consistent.
    def execute(candidate)
      accepted = @game.raw_actions.dup
      begin
        action = Engine::Action::Base.action_from_h(candidate[:action], @game)
        if action.is_a?(Engine::Action::RunRoutes)
          action.routes.each(&:clear_cache!)
          action.routes.each(&:revenue)
        end
        @game.process_action(action, add_auto_actions: true).maybe_raise!
        candidate
      rescue StandardError
        @game = fresh(accepted)
        raise
      end
    end

    def advance
      rejected = []
      options = candidates
      attempts = 0
      while options.empty? && attempts < 4
        @game.round.next_entity! if @game.round.respond_to?(:next_entity!)
        attempts += 1
        options = candidates
      end
      raise "No legal candidate at #{@game.round.active_step.class}" if options.empty?

      policy = nil
      if style(@game.current_entity) == 'lmstudio' && options.size > 1
        begin
          visible = observation
          if @game.round.is_a?(Engine::Round::Draft)
            visible[:players] = visible[:players].map { |p| p.merge(privates: []) }
          end
          shortlist = options.take(12)
          request = Net::HTTP::Post.new('/v1/chat/completions', 'Content-Type' => 'application/json')
          request.body = JSON.generate(model: config['model'], temperature: 0, max_tokens: 256,
            response_format: { type: 'json_schema', json_schema: { name: 'decision_1846', strict: true,
              schema: { type: 'object', properties: { index: { type: 'integer', minimum: 0, maximum: shortlist.size - 1 },
                reason: { type: 'string' } }, required: %w[index reason], additionalProperties: false } } },
            messages: [{ role: 'system', content: 'You play 1846. Choose one proposed action. Return only JSON {"index": integer, "reason": "brief rationale"}. Index is zero-based. Candidates are heuristic proposals subject to engine validation. Do not invent actions.' },
                       { role: 'user', content: JSON.generate(state: visible, board: board,
                         candidates: shortlist.each_with_index.map { |c, i| { index: i, action: c[:action] } }) }])
          http = Net::HTTP.new('127.0.0.1', 1234, nil)
          http.open_timeout = 2
          http.read_timeout = 20
          response = http.request(request)
          raise "HTTP #{response.code}" unless response.code == '200'
          content = JSON.parse(response.body).dig('choices', 0, 'message', 'content')
          answer = JSON.parse(content[/\{.*\}/m])
          index = Integer(answer.fetch('index'))
          raise 'Invalid candidate index' unless index.between?(0, shortlist.size - 1)
          selected = shortlist[index]
          options = [selected] + options.reject { |c| c == selected }
          policy = { source: 'lmstudio', model: config['model'], reason: answer['reason'].to_s[0, 400] }
        rescue StandardError => error
          policy = { source: 'heuristic_fallback', error: error.message }
        end
      end
      options.each do |candidate|
        begin
          execute(candidate)
          return { chosen: candidate, candidates: options.take(20), candidate_count: options.size,
                   rejected: rejected, policy: policy }
        rescue StandardError => error
          rejected << { action: candidate[:action], error: error.message }
        end
      end
      raise "No legal bot candidate at #{@game.round.active_step.class}: #{rejected.map { |r| r[:error] }.uniq.join('; ')}"
    end

    def observation
      g = @game
      { turn: g.turn, round: g.round.name, round_num: g.round.round_num, phase: g.phase.name,
        entity: g.finished ? nil : g.current_entity&.id,
        step: g.finished ? nil : g.round.active_step&.description,
        action_count: g.current_action_id, bank: g.bank.cash, finished: g.finished,
        end_reason: g.game_end_reason, result: g.result,
        players: g.players.map { |p| { id: p.id, name: p.name, cash: p.cash, value: g.player_value(p), strategy: style(p),
          privates: p.companies.map(&:name), shares: g.corporations.to_h { |c| [c.id, p.percent_of(c)] } } },
        tile_slots: begin
          step = g.round.active_step
          entity = g.current_entity
          if step.respond_to?(:get_tile_lay) && entity&.corporation?
            lay = step.get_tile_lay(entity)
            lay ? { corp: entity.id, lay: !!lay[:lay], upgrade: !!lay[:upgrade] } : nil
          end
        end,
        corporations: (g.corporations + g.minors).map { |c| { id: c.id, name: c.name, cash: c.cash,
          privates: c.companies.map { |co| { id: co.id, name: co.name } },
          owner: c.owner.respond_to?(:id) ? c.owner.id : (c.receivership? ? 'market' : nil),
          price: c.respond_to?(:share_price) ? c.share_price&.price : nil,
          color: c.color.to_s, trains: c.trains.map(&:name), floated: c.floated?,
          stations: c.tokens.select(&:used).map { |t| t.city&.hex&.id } } } }
    end

    def board
      P1846.board(@game)
    end

    def export
      { id: "1846#{@seed}", title: '1846', description: '1846 local AI self-play',
        players: @names.map { |id, name| { id: id, name: name } },
        settings: { seed: @seed, optional_rules: [] }, actions: @game.raw_actions,
        status: @game.finished ? 'finished' : 'active', result: @game.result }
    end
  end
end

if $PROGRAM_NAME == __FILE__
  STDOUT.sync = true
  config = ARGV[0] ? JSON.parse(File.read(ARGV[0], encoding: 'UTF-8')) : {}
  bot = Arena1846::Bot.new(config)
  begin
    puts JSON.generate(event: 'state', state: bot.observation, board: bot.board, game: bot.export)
    until bot.game.finished
      raise 'Action limit reached; this is not a completed game' if bot.game.current_action_id >= config.fetch('max_actions', 3000)
      before = bot.observation
      decision = bot.advance
      puts JSON.generate(event: 'transition', observation: before, decision: decision,
                         state: bot.observation, board: bot.board,
                         accepted_action: bot.game.raw_actions.last,
                         logs: bot.game.log.select { |l| l.action_id >= bot.game.current_action_id }.map(&:message))
    end
    raise 'Engine watchdog ended the game (DNF)' if bot.game.game_end_reason == :dnf
    puts JSON.generate(event: 'complete', state: bot.observation, game: bot.export,
                       log: bot.game.log.map(&:message))
  rescue StandardError => e
    puts JSON.generate(event: 'error', message: e.message, backtrace: e.backtrace.take(8), game: bot.export)
    exit 1
  end
end