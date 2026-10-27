# frozen_string_literal: true

require_relative 'actions'

# Rule-aware heuristic policy. It only ranks candidates that the engine has
# already accepted as legal; the learning pipeline replaces these priors with a
# trained policy net as checkpoints improve.
module P1846
  module Policy
    PRIORITY_COMPANIES = {
      'MS' => 40, 'BIG4' => 34, 'C&WI' => 32, 'MC' => 30, 'O&I' => 30,
      'LSL' => 26, 'MAIL' => 24, 'TBC' => 22, 'SC' => 20, 'MPC' => 16, 'LM' => 14, 'BT' => 12,
    }.freeze

    module_function

    def next_train_price(game)
      train = game.depot.upcoming.first
      return 0 unless train

      train.variants.map { |_, v| v[:price] }.min
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
      score = 10.0
      score += 26 if info[:upgrade]
      score += city_value(hex, game) * 0.7
      score += east_west_potential(hex, game) * 0.5
      score -= cost * 0.28
      # Keep a train-buying reserve: track is worth less than a train.
      reserve = entity.trains.empty? ? next_train_price(game) : 100
      score -= 40 if entity.cash - cost < reserve
      # Prefer hexes touching our own tokens.
      tokens = entity.tokens.select(&:used).map { |t| t.city&.hex }
      score += 12 if tokens.compact.any? { |h| h.neighbors.values.include?(hex) }
      score += 6 if hex.tile.cities.any? && info[:upgrade]
      score
    end

    def score_place_token(game, entity, candidate)
      info = candidate[:info]
      hex = game.hex_by_id(info[:hex])
      city = hex.tile.cities[info[:city] || 0]
      score = 20.0 + city.route_revenue(game.phase, P1846.display_train(game)) * 0.8
      opponents = city.tokens.compact.reject { |t| t.corporation == entity }.map(&:corporation)
      score += 16 * opponents.size # blocking is valuable
      score += east_west_potential(hex, game) * 0.6
      score -= (candidate[:cost] || 0) * 0.22
      score += 8 if info[:reserved] || info[:teleport]
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
      score += info[:distance].to_f * 3
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
      case candidate[:type]
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
    end
  end
end
