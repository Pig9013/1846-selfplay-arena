# frozen_string_literal: true

require 'json'
require 'socket'
require 'fileutils'
require_relative '../arena'
require_relative 'human_ui'

# Tiny local HTTP bridge for the "human vs 2 AI" window.
# GET  /state   -> game + candidates for the human seat
# POST /choose  {"index": N} -> execute that candidate, then let the AI seats move
# GET  /health
module P1846
  module HumanHTTP
    module_function

    # The arena page lives on another port, so replies must be CORS-legal and
    # OPTIONS preflights for JSON POSTs must succeed.
    CORS_HEADERS = "Access-Control-Allow-Origin: *\r\n" \
                   "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n" \
                   "Access-Control-Allow-Headers: Content-Type\r\n" \
                   "Access-Control-Max-Age: 600\r\n"
    REASONS = { 200 => 'OK', 204 => 'No Content', 404 => 'Not Found', 500 => 'Internal Server Error' }.freeze

    def write_response(client, status, payload)
      preflight = status == 204
      head = +"HTTP/1.1 #{status} #{REASONS.fetch(status, 'OK')}\r\n"
      head << CORS_HEADERS
      unless preflight
        head << "Content-Type: application/json; charset=utf-8\r\n"
        head << "Content-Length: #{payload.bytesize}\r\n"
      end
      head << "Connection: close\r\n\r\n"
      client.write(head)
      client.write(payload) unless preflight
    rescue Errno::EPIPE, Errno::ECONNRESET, Errno::ENOTCONN, IOError
      # The browser hung up (navigation, aborted fetch, preconnect). Never let
      # that take the whole game server down: the next request starts fresh.
      nil
    end

    def player_of(entity)
      return entity if entity&.player?

      entity&.player
    end

    class Session
      attr_reader :bot, :human_seat, :samples

      def initialize(config)
        @config = config
        @human_seat = config.fetch('human_seat', '1').to_s
        P1846::HumanUI.human_seat = @human_seat
        @bot = Arena1846::Bot.new(config)
        @samples = []
        @finished = false
        @saved = false
        @out = config.fetch('out', 'train/human_data')
        # Default next to the runs\human session so the platform needs no
        # extra config: the written record is the full action log.
        @record_dir = config['record_dir'] || File.join(File.expand_path('..', __dir__), 'runs', 'human')
        @seed = config.fetch('seed', 0)
        @log = []
        @history = []
        @offers = nil
        @board_cache = nil
        @stamp = nil
        @pending = 0
        @log << { n: 0, actor: '', text: "对局开始 · 种子 #{@seed} · #{config.fetch('players', 3)} 人",
                  detail: [] }
        advance_ai
      end

      # Execute one candidate and append the human-facing log line only when the
      # engine accepted it; rejected proposals leave no trace in the record.
      def play(candidate)
        g = @bot.game
        before = g.current_action_id
        label, = P1846::HumanUI.describe(candidate, g)
        actor = candidate[:action]['entity'].to_s
        begin
          @bot.execute(candidate)
        rescue StandardError
          raise
        end
        settle_round
        after = @bot.game.current_action_id
        detail = @bot.game.log.select { |l| l.action_id > before && l.action_id <= after }.map(&:message)
        @log << { n: after, actor: actor, text: label, detail: detail }
        @pending += 1
        write_record if @record_dir && (@pending % 40).zero?
        candidate
      end

      def player
        step = @bot.game.round.active_step
        step && P1846::HumanHTTP.player_of(step.current_entity)
      end

      # Raw candidates, with company purchases expanded into a price ladder:
      # 1846 lets a corporation buy a player's private for anything from $1 to
      # the company's printed value, so one "$1" proposal is not enough.
      def offers
        key = [@bot.game.current_action_id, @bot.game.round.object_id]
        return @offers[1] if @offers && @offers[0] == key

        list = []
        @bot.candidates.each do |candidate|
          if candidate[:type].to_s == 'buy_company'
            list.concat(company_prices(candidate))
          else
            list << candidate
          end
        end
        @offers = [key, list]
        @offers[1]
      end

      def company_prices(candidate)
        game = @bot.game
        info = candidate[:info] || {}
        company = game.company_by_id(info[:company])
        entity_id = candidate[:action]['entity'].to_s
        buyer = game.corporations.find { |c| c.id == entity_id } ||
                game.minors.find { |m| m.id == entity_id }
        return [candidate] unless company && buyer

        min = company.min_price.to_i
        max = [company.max_price(buyer).to_i, min].max
        step = max >= 40 ? 5 : 1
        prices = [min]
        price = (min / step + 1) * step
        while price < max
          prices << price
          price += step
        end
        prices << max
        prices.uniq.filter_map do |price|
          next if price < min

          action = Engine::Action::BuyCompany.new(buyer, company: company, price: price)
          candidate.merge(action: action.to_h, cost: price,
                          info: (candidate[:info] || {}).merge(price: price))
        rescue StandardError
          nil
        end
      end

      def human_turn?
        return false if @finished

        step = @bot.game.round.active_step
        return false unless step

        P1846::HumanHTTP.player_of(step.current_entity)&.id.to_s == @human_seat
      end

      # Keep the table moving:
      #  * a bare round.next_entity! can finish a round without the engine's
      #    transition hook, leaving no active step at all;
      #  * a seat can end up current with no legal action (no cash, nothing to
      #    sell), where the engine waits for an action that cannot exist.
      # Both would strand the browser on "AI 行动中" forever, so heal them here.
      def settle_round
        g = @bot.game
        guard = 0
        loop do
          break if g.finished

          if g.round.finished?
            g.transition_to_next_round!
          else
            step = g.round.active_step
            break unless step

            entity = step.current_entity
            break unless entity

            # A player can act through a private/minor they own (C&WI track,
            # company tokens); do not skip them just because the player object
            # itself has no action.
            actors = [entity]
            actors += entity.companies if entity.respond_to?(:companies)
            actors += g.minors.select { |m| m.owner == entity }
            break if actors.any? { |actor| !step.actions(actor).empty? }

            g.round.next_entity!
          end
          guard += 1
          raise 'settle guard' if guard > 30
        end
      rescue StandardError => error
        warn "settle_round: #{error.class}: #{error.message}"
      end

      def buys_human_company?(candidate)
        return false unless candidate[:type].to_s == 'buy_company'

        company = @bot.game.company_by_id((candidate[:info] || {})[:company])
        company && company.owner && company.owner.id.to_s == @human_seat
      end

      def advance_ai
        guard = 0
        until @bot.game.finished
          guard += 1
          raise 'action guard' if guard > 5000

          settle_round
          list = @bot.candidates
          # The AI seats do not force money out of the human's pocket: a
          # purchase of the human's private company needs the human's consent,
          # so the robots simply never propose one.
          list = list.reject { |candidate| buys_human_company?(candidate) } unless list.empty?
          if list.empty?
            @bot.advance
            settle_round
            next
          end
          break if human_turn?

          begin
            play(list.first)
          rescue StandardError => error
            step = @bot.game.round.active_step
            warn JSON.generate(event: 'advance_error', message: error.message,
                               step: step.class.name, entity: step.current_entity&.id,
                               players: @bot.game.players.map { |p| [p.id, p.passed?] },
                               actions: @bot.game.players.to_h { |p| [p.id, step.actions(p)] })
            @bot.advance
            settle_round
          end
        end
        finish if @bot.game.finished
      end

      def finish
        return if @finished

        @finished = true
        save_samples
        write_record
        archive_record
      end

      # Keep finished games: runs/human/* is overwritten by the next table, so
      # the archive holds one file pair per completed game.
      def archive_record
        return unless @record_dir

        dir = File.join(@record_dir, 'archive')
        FileUtils.mkdir_p(dir)
        base = File.join(dir, "#{@seed}-#{Time.now.strftime('%Y%m%d-%H%M%S')}")
        FileUtils.cp(File.join(@record_dir, '对局日志.txt'), "#{base}.txt") if File.file?(File.join(@record_dir, '对局日志.txt'))
        FileUtils.cp(File.join(@record_dir, 'game.json'), "#{base}.json") if File.file?(File.join(@record_dir, 'game.json'))
      end

      # Full-fidelity record: every accepted action, the engine's own log lines
      # (token placements, floats, price moves) and our readable Chinese lines.
      # The 18xx.games site log drops these details; this file keeps them.
      def write_record
        return unless @record_dir

        FileUtils.mkdir_p(@record_dir)
        g = @bot.game
        lines = ["1846 · 人类 vs AI  种子 #{@seed}  人类席位 #{@human_seat}", '']
        @log.each do |entry|
          lines << format('%3d. %s', entry[:n], entry[:text])
          Array(entry[:detail]).each { |message| lines << "      · #{message}" }
        end
        lines << ''
        lines << "结束原因：#{g.game_end_reason}" if g.finished
        lines << "结果：#{g.result.map { |id, value| "#{id} $#{value}" }.join('  ')}" if g.finished
        File.write(File.join(@record_dir, '对局日志.txt'), lines.join("\n") + "\n", encoding: 'UTF-8')
        File.write(File.join(@record_dir, 'game.json'), JSON.pretty_generate(
          seed: @seed, human_seat: @human_seat, finished: @finished,
          result: g.finished ? g.result : nil, end_reason: g.game_end_reason.to_s,
          actions: g.raw_actions, log: @log
        ), encoding: 'UTF-8')
      rescue StandardError => error
        warn "record write failed: #{error.message}"
      end

      def save_samples
        return if @saved

        @saved = true
        FileUtils.mkdir_p(@out)
        scores = @bot.game.result.transform_values(&:to_f)
        mean = scores.values.sum / [scores.size, 1].max
        var = scores.values.sum { |v| (v - mean)**2 } / [scores.size, 1].max
        std = Math.sqrt(var).clamp(1.0, Float::INFINITY)
        z = scores.transform_values { |v| ((v - mean) / std).clamp(-2.0, 2.0) }
        id = format('%s-human-http-%s', @seed, @human_seat)
        File.open(File.join(@out, "#{id}.jsonl"), 'w') do |file|
          file.puts JSON.generate(type: 'meta', seed: @seed, players: @bot.config.fetch('players', 3),
                                  human_seat: @human_seat, feature_version: P1846::FEATURE_VERSION,
                                  degenerate: false, low_quality: false,
                                  end_reason: @bot.game.game_end_reason.to_s)
          @samples.each do |sample|
            file.puts JSON.generate(type: 'decision', actor: sample[:actor],
                                    state: sample[:state].map { |v| v.round(4) },
                                    actions: sample[:actions].map { |a| a.map { |v| v.round(4) } },
                                    chosen: sample[:chosen], prior: sample[:prior])
          end
          file.puts JSON.generate(type: 'result', scores: scores, z: z,
                                  winner: scores.max_by { |_, v| v }&.first,
                                  margin: 0, winner_weight: 1)
        end
      end

        # Never offer a tile the acting treasury cannot pay for: the engine
        # rejects it and the player would see a pointless refusal.
      def unaffordable?(candidate)
        return false unless candidate[:type].to_s == 'lay_tile'

        entity_id = candidate[:action]['entity'].to_s
        actor = @bot.game.corporations.find { |c| c.id == entity_id } ||
                @bot.game.minors.find { |m| m.id == entity_id }
        actor ? candidate[:cost].to_i > actor.cash : false
      end

      def board_json
        key = @bot.game.current_action_id
        return @board_cache[1] if @board_cache && @board_cache[0] == key

        @board_cache = [key, P1846.board(@bot.game)]
        @board_cache[1]
      end

      # Owners can be players, corporations (cross-holding) or the share pool
      # (receivership); only the first two have an id.
      def holder_id(entity)
        return nil if entity.nil?
        return entity.id if entity.respond_to?(:player?) && (entity.player? || entity.corporation?)

        'pool'
      end

      def players_json(g)
        g.players.map do |p|
          {
            id: p.id,
            name: p.id.to_s == @human_seat ? '你' : p.name,
            cash: p.cash,
            value: g.player_value(p),
            shares: g.corporations.filter_map do |corp|
              percent = p.percent_of(corp)
              { corp: corp.id, percent: percent } if percent.to_i.positive?
            end,
            privates: p.companies.map { |c| { id: c.id, name: c.name, revenue: (c.respond_to?(:revenue) ? c.revenue : 0) } },
          }
        end
      end

      def corporations_json(g)
        acting = g.round.active_step&.current_entity
        (g.corporations + g.minors).map do |corp|
          {
            id: corp.id,
            name: corp.name,
            color: corp.color.to_s,
            type: corp.respond_to?(:minor?) && corp.minor? ? 'minor' : 'corporation',
            owner: holder_id(corp.owner),
            floated: corp.respond_to?(:floated?) ? corp.floated? : true,
            cash: corp.cash,
            par: (corp.respond_to?(:par_price) ? corp.par_price&.price : nil),
            price: (corp.respond_to?(:share_price) ? corp.share_price&.price : nil),
            trains: corp.trains.map(&:name),
            tokens: corp.tokens.select(&:used).map { |t| t.city&.hex&.id }.compact,
            holders: (corp.respond_to?(:share_holders) ? corp.share_holders.map { |h, pct|
              key = h.is_a?(Symbol) ? h.to_s : holder_id(h)
              key = 'ipo' if key == corp.id
              key = 'market' if key == 'pool'
              [key, pct]
            }.to_h : {}),
            acting: acting == corp,
          }
        end
      end

      def privates_json(g)
        minors = g.minors.map(&:id)
        g.companies.reject { |c| c.name.start_with?('Pass') || minors.include?(c.id) }.map do |company|
          { id: company.id, name: company.name, owner: holder_id(company.owner),
            revenue: (company.respond_to?(:revenue) ? company.revenue : 0),
            value: (company.respond_to?(:value) ? company.value : nil),
            min_bid: (company.respond_to?(:min_bid) ? company.min_bid : nil) }
        end
      end

      def market_json(g)
        row = g.stock_market.market.first
        cells = row.map { |sp| { price: sp.price, par: sp.type == :par } }
        {
          cells: cells,
          corporations: g.corporations.filter_map do |corp|
            next unless corp.share_price

            # Match by price: 1846 has one row, and its coordinates are not
            # guaranteed to index the same array the UI renders.
            { id: corp.id, color: corp.color.to_s, price: corp.share_price.price,
              index: cells.index { |cell| cell[:price] == corp.share_price.price } }
          end,
        }
      end

      def depot_json(g)
        g.depot.upcoming.group_by(&:name).map do |name, list|
          { name: name, price: list.first.price, distance: list.first.distance, count: list.size }
        end
      end

      def snapshot
        g = @bot.game
        settle_round
        # Polling must not rebuild the whole board every second: the payload can
        # only change when the engine advances (or the game ends).
        key = [g.current_action_id, g.round.object_id, @finished]
        cached = @snapshot_cache
        return cached[1] if cached && cached[0] == key

        step = g.round.active_step
        entity = step&.current_entity
        projected = { groups: [], candidates: [] }
        if human_turn?
          projected = P1846::HumanUI.project(offers, g, skip: method(:unaffordable?))
        end
        json = {
          finished: @finished,
          human_turn: human_turn?,
          action_count: g.current_action_id,
          you: @human_seat,
          round: g.round.name,
          round_num: (g.round.respond_to?(:round_num) ? g.round.round_num : nil),
          phase: g.phase.name,
          turn: g.turn,
          step: P1846::HumanUI.step_label(step),
          step_class: step ? step.class.name.split('::').last.to_s : '',
          entity: entity&.id,
          # The company the actions belong to: 1846 lets a private (C&WI) or a
          # minor act while round.current_entity is still the owning player.
          acting: projected[:candidates].first&.dig(:entity) || entity&.id,
          entity_type: entity.respond_to?(:corporation?) && entity.corporation? ? 'corporation' : 'player',
          bank: g.bank.cash,
          players: players_json(g),
          corporations: corporations_json(g),
          privates: privates_json(g),
          market: market_json(g),
          depot: depot_json(g),
          board: board_json,
          log: @log.last(200),
          groups: projected[:groups],
          candidates: projected[:candidates],
          undo: @history.size,
          result: @finished ? g.result : nil,
        }.to_json
        @snapshot_cache = [key, json]
        json
      end

      # pick is an index into the raw candidate list (the browser sends the
      # "pick" value it received), so the display can de-duplicate and group
      # without ever losing track of which engine action is meant.
      def choose(pick)
        raise 'not human turn' unless human_turn?

        list = offers
        pick = pick.to_i
        raise 'bad pick' unless pick.between?(0, list.size - 1)
        check_seller!(list[pick])
        @history << { actions: @bot.game.raw_actions.dup, log: @log.size, samples: @samples.size }

        step = @bot.game.round.active_step
        raise '当前没有可行动的步骤' unless step

        entity = step.current_entity
        player = P1846::HumanHTTP.player_of(entity)
        state = P1846.state_features(@bot.game, entity)
        # The behaviour-cloning format keeps at most 12 actions per decision:
        # put the human's choice first so the label is never truncated away.
        order = [pick] + (0...list.size).reject { |i| i == pick }.first(11)
        actions = order.map { |i| P1846.action_features(@bot.game, list[i], entity) }
        prior = order.map { |i| list[i][:score].to_f.round(3) }
        play(list[pick])
        @samples << { actor: player.id.to_s, state: state, actions: actions,
                      chosen: 0, prior: prior }
        @offers = nil
        advance_ai
        { ok: true, snapshot: JSON.parse(snapshot) }.to_json
      rescue StandardError => error
        @history.pop if @history.last && @history.last[:log] == @log.size
        { ok: false, error: error.message, snapshot: JSON.parse(snapshot) }.to_json
      end

      # Buying a private from another player needs that player's consent. The
      # AI seats value the company at its printed value (they will take a 25%
      # haircut, not the $1 minimum).
      def check_seller!(candidate)
        return unless candidate[:type].to_s == 'buy_company'

        company = @bot.game.company_by_id((candidate[:info] || {})[:company])
        return unless company

        owner = company.owner
        return if owner.nil? || owner.id.to_s == @human_seat

        price = candidate[:cost].to_i
        floor = (company.value.to_f * 0.75).round
        return if price >= floor

        raise "#{owner.name} 不接受 $#{price}：他给 #{company.name} 的估值是 #{company.value}（至少要 $#{floor}）"
      end

      # Take the last human move back: the engine replays the recorded action
      # list up to the saved checkpoint, which restores every counter exactly.
      def undo
        checkpoint = @history.pop
        raise '没有可以撤回的步骤了' unless checkpoint

        @bot = Arena1846::Bot.new(@config)
        @bot.restore(checkpoint[:actions])
        @log = @log.first(checkpoint[:log])
        @samples = @samples.first(checkpoint[:samples])
        @finished = false
        @offers = nil
        @snapshot_cache = nil
        @board_cache = nil
        settle_round
        write_record
        { ok: true, snapshot: JSON.parse(snapshot) }.to_json
      rescue StandardError => error
        { ok: false, error: error.message, snapshot: JSON.parse(snapshot) }.to_json
      end
    end

    def serve(config)
      session = Session.new(config)
      port = Integer(config.fetch('port', 1847))
      server = TCPServer.new('127.0.0.1', port)
      puts "human-http listening on #{port}" 
      loop do
        client = server.accept
        begin
          client.timeout = 15
          request_line = client.gets.to_s.strip
          # Keep-alive preconnects and cancelled requests arrive without a
          # request line; ignore them instead of answering a ghost client.
          next if request_line.empty?

          method, path, _ = request_line.split(' ')
          headers = {}
          while (line = client.gets) && line != "\r\n"
            key, value = line.split(':', 2)
            headers[key.downcase] = value.to_s.strip if key
          end
          body = headers['content-length'] ? client.read(headers['content-length'].to_i) : ''
          # The page is served from the arena port, so every call here is a
          # cross-origin request. JSON POSTs are preflighted: answer OPTIONS or
          # the browser blocks /choose and the page only sees "Failed to fetch".
          if method == 'OPTIONS'
            write_response(client, 204, '')
            next
          end
          status, payload = if method == 'GET' && path == '/health'
                              [200, { ok: true, human_turn: session.human_turn? }.to_json]
                            elsif method == 'GET' && path == '/state'
                              [200, session.snapshot]
                            elsif method == 'POST' && path == '/choose'
                              payload = JSON.parse(body)
                              [200, session.choose(payload.fetch('pick', payload.fetch('index', 0)))]
                            elsif method == 'POST' && path == '/undo'
                              [200, session.undo]
                            else
                              [404, { error: 'not found' }.to_json]
                            end
          write_response(client, status, payload)
        rescue StandardError => error
          warn "#{error.class}: #{error.message}\n#{Array(error.backtrace).take(10).join("\n")}"
          payload = { ok: false, error: error.message }.to_json
          write_response(client, 500, payload)
        ensure
          client.close
        end
      end
    end
  end
end

if $PROGRAM_NAME == __FILE__
  P1846::HumanHTTP.serve(JSON.parse(File.read(ARGV[0], encoding: 'UTF-8')))
end
