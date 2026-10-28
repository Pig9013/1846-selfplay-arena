# frozen_string_literal: true

require_relative 'actions'
require_relative 'connectivity'
require_relative 'human_prior'

# Rule-aware heuristic policy. It only ranks candidates that the engine has
# already accepted as legal; the learning pipeline replaces these priors with a
# trained policy net as checkpoints improve.
#
# The weights below encode generic economics, not a scripted strategy:
#   1. A tile is only worth anything if its rotation actually joins the
#      company's network to the edge that faces an offboard.
#   2. Joining the missing half of an E/W pair is worth real money; the human
#      prior supplies empirical style (which hex/tile/par humans actually pick)
#      and the network learns the rest. No city is hard-coded as "must build".
module P1846
  module Policy
    PRIORITY_COMPANIES = {
      'MS' => 44, 'BIG4' => 34, 'C&WI' => 30, 'MC' => 30, 'O&I' => 30,
      'LSL' => 26, 'MAIL' => 24, 'TBC' => 22, 'SC' => 20, 'MPC' => 16, 'LM' => 14, 'BT' => 12,
    }.freeze

    module_function

    def next_train_price(game)
      train = game.depot.upcoming.first
      return 0 unless train

      train.variants.map { |_, v| v[:price] }.min
    end

    # In 1846 a 2-train is obsolete once the 5-train appears and rusts when the
    # 6-train appears. A company that spends its treasury on track just before
    # that point can be forced into an emergency issue and, if the president
    # cannot cover it, bankruptcy. Reserve the next train price instead of
    # pretending 100 is always enough.
    def train_reserve(game, entity)
      return 100 if entity.trains.empty?

      names = entity.trains.map(&:name)
      case game.phase.name
      when 'III'
        names.include?('2') ? next_train_price(game) : 100
      when 'IV'
        (names.include?('2') || names.include?('4')) ? next_train_price(game) : 100
      else
        100
      end
    end

    def city_value(hex, game)
      train = game.route_trains(game.current_entity).first || P1846.display_train(game)
      hex.tile.cities.sum { |c| c.route_revenue(game.phase, train) } +
        hex.tile.offboards.sum { |o| o.route_revenue(game.phase, train) }
    end

    def east_west_potential(hex, game)
      score = 0
      tile = hex.tile
      score += 18 if tile.offboards.any? { |o| o.groups.include?('E') }
      score += 18 if tile.label&.to_s == 'W'
      hex.neighbors.each_value do |n|
        score += 10 if n.tile.offboards.any? { |o| o.groups.include?('E') }
        score += 10 if n.tile.label&.to_s == 'W'
        score += 4 if n.tile.cities.any?
      end
      score
    end

    def score_lay_tile(game, entity, candidate)
      info = candidate[:info]
      hex = game.hex_by_id(info[:hex])
      cost = candidate[:cost] || 0
      # A tile is not a goal. Score the money it can produce now and the
      # revenue base it builds for the next OR. A long E/W line has many
      # intermediate tiles that do not touch an off-board yet; those must be
      # judged by the network they build, not by an immediate off-board flag.
      old_rev = info[:old_city_revenue].to_i
      new_rev = (info[:new_city_revenue] || city_value(hex, game)).to_i
      offboard = info[:offboard_link] ? info[:offboard_value].to_i : 0
      current = (new_rev - old_rev) + offboard
      future = (new_rev * 0.35) + (info[:through_edges].to_i * 7.0) +
               (info[:connected_edges].to_i * 4.0)
      score = 2.0
      # City tiles (especially Z/Chicago, but generic here) are the upgrades
      # worth paying for. Plain-track upgrades get a much smaller nudge; their
      # job is connecting valuable cities, not being upgraded for its own sake.
      score += info[:city_upgrade] ? 26.0 : (info[:upgrade] ? 4.0 : 0.0)
      score += current * 0.55
      score += future
      # Completing an off-board edge is worth something, but it is no longer
      # allowed to dominate the whole track decision.
      score += 10.0 if info[:offboard_link]
      score -= 8.0 if info[:points_at_offboard] && !info[:offboard_link]
      # Upgrading plain track is usually only worth it to join two valuable
      # regions or an E/W corridor. Without a city/off-board payoff, it is
      # mostly decorative; charge it accordingly (still not a hard ban).
      if info[:upgrade] && !info[:city_upgrade] && !info[:offboard_link]
        score -= 20.0
      end
      score += 4.0 if info[:ew_completion]
      score += info[:ew_approach].to_i * 1.0
      score -= cost * 0.42
      # A bare stub that neither serves a city nor joins an off-board nor runs
      # through a node is usually track sprawl. Keep it slightly negative so
      # "pass and keep the treasury" is a real option.
      if !info[:upgrade] && info[:new_city_revenue].to_i.zero? && !info[:offboard_link] &&
         info[:through_edges].to_i < 2
        score -= 10.0
      end
      # Keep a train-buying reserve: track is worth less than a train.
      reserve = entity.trains.empty? ? next_train_price(game) : train_reserve(game, entity)
      if entity.cash - cost < reserve
        # A company with no train must protect the train purchase. Once it has
        # a train, track is what turns that train into revenue; a full 40-point
        # reserve penalty made growth companies pass track and then die with a
        # train but no network.
        score -= entity.trains.empty? ? 40.0 : 12.0
      end
      # Prefer hexes touching our own tokens.
      tokens = entity.tokens.select(&:used).map { |t| t.city&.hex }
      score += 12 if tokens.compact.any? { |h| h.neighbors.values.include?(hex) }
      score += 6 if info[:city_upgrade]
      score
    end

    def score_place_token(game, entity, candidate)
      info = candidate[:info]
      hex = game.hex_by_id(info[:hex])
      city = hex.tile.cities[info[:city] || 0]
      score = 20.0 + city.route_revenue(game.phase, P1846.display_train(game)) * 0.8
      opponents = city.tokens.compact.reject { |t| t.corporation == entity }.map(&:corporation)
      score += 16 * opponents.size # blocking is valuable
      score += east_west_potential(hex, game) * 0.3
      score -= (candidate[:cost] || 0) * 0.22
      # Reserved/teleport slots are generic legal assets; the human prior and
      # the engine's city revenue decide whether this one is worth taking.
      score += 22.0 if info[:reserved] || info[:teleport]
      score
    end

    def score_dividend(game, entity, candidate)
      kind = candidate[:info][:kind]
      price = entity.share_price&.price.to_i
      treasury = entity.cash
      need = next_train_price(game)
      trains = entity.trains.size
      revenue = game.round.respond_to?(:routes) ? game.round.routes.sum(&:revenue) : 0
      if kind == 'withhold'
        return 30.0 + (trains.zero? ? 30 : 0) + (treasury < need ? 25 : 0) - (price > 180 ? 20 : 0)
      end
      pay = kind == 'payout' ? revenue / 10 : revenue / 20
      score = 25.0 + pay * 0.5
      score -= 20 if treasury < need && trains < 2
      score += 6 if price < 120 && kind == 'payout'
      score
    end

    def score_buy_train(game, entity, candidate)
      info = candidate[:info]
      price = candidate[:cost]
      score = 30.0
      score += 50 if entity.trains.empty?
      score -= price * 0.06
      score += info[:distance].to_f * 5
      score -= 20 if entity.trains.size >= 2 && price > 300
      score += 12 if candidate[:info][:variant] # 3/5 and 4/6 variants are flexible
      score
    end

    def score_par(game, entity, candidate)
      info = candidate[:info]
      corp = game.corporation_by_id(info[:corp])
      price = info[:par]
      score = 40.0
      score += 10 if corp.id == 'IC' # subsidy
      score += 6 if %w[GT C&O].include?(corp.id)
      score -= (price - 90).abs * 0.2
      score -= 45 if price < 80
      score -= 30 if entity.cash < price * 4
      score
    end

    def score_buy_shares(game, entity, candidate)
      info = candidate[:info]
      price = candidate[:cost] || 0
      return 18.0 if info[:redeem]

      corp = game.corporation_by_id(info[:corp])
      return -20.0 if entity.cash - price < 40 # keep walking-around money

      score = 14.0
      score += 12 if corp.trains.any?
      score += 4 if corp.owner == entity
      score += 5 if %w[PRR IC].include?(corp.id) # token depth / subsidy
      score -= 25 unless corp.trains.any?
      score += [corp.share_price.price, 150].min / 25.0
      score -= price * 0.05
      score
    end

    def score_sell_shares(game, entity, candidate)
      info = candidate[:info]
      return 40.0 if info[:issue] # corporation raising cash

      corp = game.corporation_by_id(info[:corp])
      score = -10.0
      score += 30 if corp.trains.empty? && corp.cash < next_train_price(game)
      score
    end

    def score_bid(game, entity, candidate)
      info = candidate[:info]
      return 1.0 if info[:blank]

      base = PRIORITY_COMPANIES[info[:company]] || 8
      base + 8.0 - (candidate[:cost] || 0) * 0.05
    end

    def score_buy_company(game, entity, candidate)
      info = candidate[:info]
      base = PRIORITY_COMPANIES[info[:company]] || 6
      return 34.0 if game.minor_by_id(info[:company])

      base * 0.7 + 8
    end

    def score(game, candidate, entity)
      base = case candidate[:type]
      when 'lay_tile' then score_lay_tile(game, entity, candidate)
      when 'place_token' then score_place_token(game, entity, candidate)
      when 'dividend' then score_dividend(game, entity, candidate)
      when 'buy_train' then score_buy_train(game, entity, candidate)
      when 'par' then score_par(game, entity, candidate)
      when 'buy_shares' then score_buy_shares(game, entity, candidate)
      when 'sell_shares' then score_sell_shares(game, entity, candidate)
      when 'bid' then score_bid(game, entity, candidate)
      when 'buy_company' then score_buy_company(game, entity, candidate)
      when 'run_routes' then 100.0
      when 'assign' then 60.0
      when 'discard_train' then 50.0
      when 'bankrupt' then 900.0
      when 'pass' then 0.0
      else 5.0
      end
      base + P1846::HumanPrior.bonus(game, entity, candidate)
    end
  end
end
