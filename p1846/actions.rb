# frozen_string_literal: true

require_relative 'board'

# Legal candidate generation. Every candidate is built from the same engine
# checks the rules use (tile availability, rotations, tokenability, share
# limits, train variants), so a proposal is legal by construction; the engine
# still validates and remains the final authority.
module P1846
  ROUTE_LIMIT = 48
  ROUTE_TIMEOUT = 1.6

  module_function

  def tile_lay_candidates(game, entity, step, list, budget: 260)
    hexes = game.hexes.select { |hex| step.tracker_available_hex(entity, hex) }
    hexes.each do |hex|
      next if hex.tile.color == :blue

      step.upgradeable_tiles(entity, hex).each do |tile|
        cost = tile_cost(game, entity, hex, tile)
        tile.legal_rotations.each do |rotation|
          tile.rotate!(rotation)
          list << { type: 'lay_tile', action: Engine::Action::LayTile.new(entity, tile: tile, hex: hex, rotation: rotation),
                    cost: cost, info: { hex: hex.id, tile: tile.name, rotation: rotation,
                                        upgrade: hex.tile.color != :white, color: tile.color.to_s } }
        end
      end
    end
    list
  end

  def token_candidates(game, entity, step, list)
    graph = game.token_graph_for_entity(entity)
    return list unless step.respond_to?(:can_place_token?) && step.can_place_token?(entity)

    nodes = graph.connected_nodes(entity)
    nodes.keys.select(&:city?).each do |city|
      next unless city.tokenable?(entity, free: false, spender: entity)

      price = city.hex.tile.cities.any? { |c| c.tokened_by?(entity) } ? 0 : nil
      list << { type: 'place_token', action: Engine::Action::PlaceToken.new(entity, city: city),
                cost: 80, info: { hex: city.hex.id, city: city.index, good: true } }
    end
    # Reserved / teleport token slots (B&O Cincinnati, PRR Ft. Wayne, ERIE Erie, IC Centralia)
    game.abilities(entity, :token) do |ability|
      next unless ability.hexes.any?

      ability.hexes.each do |hex_id|
        hex = game.hex_by_id(hex_id)
        hex.tile.cities.each_with_index do |city, index|
          next if ability.city && ability.city != index
          next unless city.tokenable?(entity, free: false, cheater: true, spender: entity)

          price = ability.price ? ability.price(nil) : 80
          if graph.reachable_hexes(entity)[hex]
            list << { type: 'place_token', action: Engine::Action::PlaceToken.new(entity, city: city),
                      cost: price, info: { hex: hex.id, city: index, reserved: true } }
          elsif ability.teleport_price
            list << { type: 'place_token', action: Engine::Action::PlaceToken.new(entity, city: city),
                      cost: ability.teleport_price, info: { hex: hex.id, city: index, teleport: true } }
          end
        end
      end
    end
    list
  end

  def route_candidates(game, entity, list)
    return list unless game.can_run_route?(entity)

    routes, timed_out = best_routes(game, entity)
    list << { type: 'run_routes', action: Engine::Action::RunRoutes.new(entity, routes: routes),
              revenue: routes.sum { |r| r.revenue }, info: { routes: routes.size, timed_out: timed_out } }
    list
  end

  # Upstream path walker (same one the website uses), then an exhaustive
  # non-overlapping combination search over the returned per-train routes.
  def best_routes(game, entity)
    router = Engine::AutoRouter.new(game)
    groups, timed_out = router.path(game.route_trains(entity).sort_by(&:id), entity,
                                    path_timeout: ROUTE_TIMEOUT, route_limit: ROUTE_LIMIT)
    best = []
    value = 0
    search = lambda do |index, chosen|
      if index == groups.size
        revenue = router.real_revenue(chosen)
        if revenue > value
          value = revenue
          best = chosen.dup
        end
        return
      end
      search.call(index + 1, chosen)
      groups.values[index].each do |route|
        next if chosen.any? { |r| r.bitfield.zip(route.bitfield).any? { |a, b| a && b && (a & b) != 0 } }

        search.call(index + 1, chosen + [route])
      end
    end
    search.call(0, [])
    router.real_revenue(best)
    [best, timed_out]
  end

  def share_candidates(game, entity, step, list)
    types = step.actions(entity)
    if types.include?('buy_shares')
      if entity.corporation?
        step.redeemable_shares(entity).each do |bundle|
          list << { type: 'buy_shares', action: Engine::Action::BuyShares.new(entity, shares: bundle.shares,
                                                                              percent: bundle.percent,
                                                                              share_price: bundle.share_price),
                    cost: bundle.price, info: { redeem: true, corp: bundle.corporation.id } }
        end
      else
        game.corporations.select(&:ipoed).each do |corp|
          (corp.ipo_shares + game.share_pool.shares_of(corp)).each do |share|
            next if share.president && !corp.receivership?

            bundle = share.to_bundle
            next unless step.can_buy?(entity, bundle)

            list << { type: 'buy_shares', action: Engine::Action::BuyShares.new(entity, shares: [share]),
                      cost: bundle.price, info: { corp: corp.id, percent: bundle.percent, president: share.president } }
          end
        end
      end
    end
    return list unless types.include?('sell_shares')

    bundles = if entity.corporation?
                step.issuable_shares(entity)
              else
                game.corporations.flat_map { |corp| game.bundles_for_corporation(entity, corp) }.select do |bundle|
                  step.can_sell?(entity, bundle)
                end
              end
    bundles.each do |bundle|
      list << { type: 'sell_shares', action: Engine::Action::SellShares.new(entity, shares: bundle.shares,
                                                                           percent: bundle.percent,
                                                                           share_price: bundle.share_price),
                revenue: bundle.price, info: { corp: bundle.corporation.id, percent: bundle.percent, issue: entity.corporation? } }
    end
    list
  end

  def train_candidates(game, entity, step, list)
    types = step.actions(entity)
    return list unless types.include?('buy_train')

    # The treasury pays for a normal purchase; the president may only add cash
    # during an emergency buy. Minors' money is not spendable here.
    cash = entity.cash
    cash += entity.owner.cash if entity.corporation? && step.respond_to?(:president_may_contribute?) &&
                                 step.president_may_contribute?(entity)
    step.buyable_trains(entity).select(&:from_depot?).each do |train|
      step.buyable_train_variants(train, entity).each do |variant|
        price = variant[:price]
        next if price > cash

        list << { type: 'buy_train', action: Engine::Action::BuyTrain.new(entity, train: train, price: price, variant: variant[:name]),
                  cost: price, info: { train: train.name, variant: variant[:name], distance: train.distance, first: entity.trains.empty? } }
      end
    end
    # 1846 has no train trading between corporations (EBUY_FROM_OTHERS = :never,
    # and the rules only move trains through Independent Railroad purchases).
    list
  end

  # Some steps (Assign, SpecialTrack) act on behalf of a company the current
  # player controls; the round reports the player as current entity but only
  # the company has legal actions.
  def acting_entity(game, step)
    current = step.current_entity
    return current if current && !step.actions(current).empty?

    pool = [current].compact
    pool += current.companies if current.respond_to?(:companies) && current.player?
    pool += game.minors.select { |m| m.owner == current }
    pool.find { |candidate| !step.actions(candidate).empty? } || current
  end

  def candidates(game)
    step = game.round.active_step
    entity = acting_entity(game, step)
    types = step.actions(entity)
    list = []
    srand_cache = nil

    if types.include?('bid')
      step.available.each do |company|
        list << { type: 'bid', action: Engine::Action::Bid.new(entity, company: company, price: company.min_bid),
                  cost: company.min_bid, info: { company: company.id, blank: company.name.include?('Pass') } }
      end
    end

    if types.include?('par')
      owned = game.corporations.count { |c| c.owner == entity }
      game.corporations.each do |corp|
        next unless game.can_par?(corp, entity)
        next unless owned.zero? || entity.cash > 500

        step.get_par_prices(entity, corp).each do |price|
          list << { type: 'par', action: Engine::Action::Par.new(entity, corporation: corp, share_price: price),
                    cost: price.price * 2, info: { corp: corp.id, par: price.price } }
        end
      end
    end

    share_candidates(game, entity, step, list)
    tile_lay_candidates(game, entity, step, list) if types.include?('lay_tile')
    token_candidates(game, entity, step, list) if types.include?('place_token')
    route_candidates(game, entity, list) if types.include?('run_routes')

    if types.include?('dividend') && step.respond_to?(:dividend_types)
      step.dividend_types.each do |kind|
        list << { type: 'dividend', action: Engine::Action::Dividend.new(entity, kind: kind.to_s), info: { kind: kind.to_s } }
      end
    end

    if types.include?('discard_train')
      entity.trains.each do |train|
        list << { type: 'discard_train', action: Engine::Action::DiscardTrain.new(entity, train: train),
                  info: { train: train.name } }
      end
    end

    train_candidates(game, entity, step, list)

    if types.include?('buy_company')
      game.purchasable_companies(entity).each do |company|
        price = company.min_price
        next if price > game.buying_power(entity)
        # Buying an Independent Railroad hands over a 2-train: it needs a free slot.
        if game.minor_by_id(company.id) && step.respond_to?(:room?) && !step.room?(entity)
          next
        end

        list << { type: 'buy_company', action: Engine::Action::BuyCompany.new(entity, company: company, price: price),
                  cost: price, info: { company: company.id } }
      end
    end

    if types.include?('assign')
      game.companies.each do |company|
        next unless company.owner == entity || entity == company

        game.abilities(company, :assign_hexes) do |ability|
          ability.hexes.each do |hex_id|
            hex = game.hex_by_id(hex_id)
            next if hex.assigned?(company.id)

            list << { type: 'assign', action: Engine::Action::Assign.new(company, target: hex),
                      info: { company: company.id, hex: hex.id } }
          end
        end
        game.abilities(company, :assign_corporation) do |ability|
          (game.corporations + game.minors).each do |corp|
            next if corp.closed? || corp.assigned?(company.id)

            list << { type: 'assign', action: Engine::Action::Assign.new(company, target: corp),
                      info: { company: company.id, corp: corp.id } }
          end
        end
      end
    end

    if entity.corporation? && types.include?('bankrupt') && game.can_go_bankrupt?(entity.owner, entity)
      list << { type: 'bankrupt', action: Engine::Action::Bankrupt.new(entity), info: {} }
    end

    list << { type: 'pass', action: Engine::Action::Pass.new(entity), info: {} } if types.include?('pass')

    # to_h caches its hash; a cached hash computed before process_action assigns
    # the action id would miss "id", so clear it again after de-duplicating.
    if list.empty?
      warn JSON.generate(step: step.class.name, current: step.current_entity&.id, acts: step.actions(step.current_entity),
                         companies: game.companies.map { |c| [c.id, c.owner&.id, step.actions(c)] },
                         minors: game.minors.map { |m| [m.id, m.owner&.id, step.actions(m)] },
                         corps: game.corporations.map { |c| [c.id, step.actions(c)] }.first(3))
    end
    list = list.uniq { |c| c[:action].to_h }
    list.each { |c| c[:action].clear_cache }
    list
  end
end
