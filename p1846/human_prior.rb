# frozen_string_literal: true

require 'json'

# Soft human-frequency prior. It is deliberately NOT a rulebook: it only nudges
# the heuristic toward actions that appear often in 665 human 18xx.games logs.
# The weight is configurable (default 10 points, 0 disables it), and the neural
# policy can override it. Chicago/Z/EW are not special-cased here; they appear
# only through the empirical hex/tile frequencies in train/human_prior.json.
module P1846
  module HumanPrior
    PATH = File.expand_path('../train/human_prior.json', __dir__)
    PRIVATE_SYMS = {
      'Michigan Southern (Minor)' => 'MS', 'Big 4 (Minor)' => 'BIG4',
      'Chicago and Western Indiana' => 'C&WI', 'Mail Contract' => 'MAIL',
      'Tunnel Blasting Company' => 'TBC', 'Boomtown' => 'BT',
      'Michigan Central' => 'MC', 'Ohio & Indiana' => 'O&I',
      'Little Miami' => 'LM', 'Lake Shore Line' => 'LSL',
      'Steamboat Company' => 'SC', 'Meat Packing Company' => 'MPC',
      'MS' => 'MS', 'BIG4' => 'BIG4', 'C&WI' => 'C&WI', 'MAIL' => 'MAIL',
      'TBC' => 'TBC', 'BT' => 'BT', 'MC' => 'MC', 'O&I' => 'O&I',
      'LM' => 'LM', 'LSL' => 'LSL', 'SC' => 'SC', 'MPC' => 'MPC',
    }.freeze

    @data = nil
    @weight = 10.0

    module_function

    def weight
      @weight
    end

    def weight=(value)
      @weight = value.to_f
    end

    def data
      @data ||= begin
        JSON.parse(File.read(PATH, encoding: 'UTF-8'))
      rescue StandardError
        {}
      end
    end

    def value(table, key)
      return 0.0 unless table.is_a?(Hash) && key

      (table[key] || 0.0).to_f
    end

    def bonus(game, _entity, candidate)
      return 0.0 if @weight <= 0.0

      info = candidate[:info] || {}
      type = candidate[:type].to_s
      phase = game.phase.name
      raw =
        case type
        when 'lay_tile'
          h = value(data.dig('phase_hex_norm', phase), info[:hex])
          t = value(data.dig('phase_tile_norm', phase), info[:tile])
          (h + (0.7 * t)) * (phase == 'I' ? 1.0 : 0.75)
        when 'place_token'
          value(data.dig('phase_hex_norm', phase), info[:hex]) * 0.7
        when 'par'
          value(data.dig('par_norm', info[:corp]), info[:par].to_s) * 0.9
        when 'bid', 'buy_company'
          sym = PRIVATE_SYMS[info[:company]] || info[:company]
          value(data['private_norm'], sym) * 0.8
        when 'buy_train'
          value(data.dig('train_norm', phase), info[:train]) * 0.6
        when 'dividend'
          kind = info[:kind].to_s == 'payout' ? 'div' : info[:kind].to_s
          value(data.dig('dividend_norm', phase), kind) * 0.5
        else
          0.0
        end
      raw * @weight
    end
  end
end
