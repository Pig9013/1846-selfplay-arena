# frozen_string_literal: true

require_relative 'actions'
require 'net/http'
require 'json'

# Fixed-size feature encoding shared by the self-play workers (Ruby) and the
# trainer (Python). Layout changes must bump FEATURE_VERSION and be mirrored in
# train/features.py.
module P1846
  FEATURE_VERSION = 1
  STATE_SIZE = 128
  ACTION_SIZE = 40
  TYPES = %w[lay_tile place_token run_routes dividend buy_train par buy_shares sell_shares bid
             buy_company assign pass discard_train bankrupt].freeze
  DIVIDENDS = %w[payout half withhold].freeze
  HEX_COLORS = %w[white yellow green brown gray red blue].freeze

  module_function

  def state_features(game, entity)
    vec = []
    4.times { |i| vec << (game.phase.name == %w[I II III IV][i] ? 1.0 : 0.0) }
    vec << game.turn.to_f / 20
    vec << (game.round.round_num || 0).to_f / 6
    vec << game.bank.cash.to_f / 9000
    actor = entity.player? ? entity : entity.player
    game.corporations.first(9).each do |corp|
      vec << corp.cash.to_f / 600
      vec << corp.trains.size.to_f / 4
      vec << corp.trains.sum { |t| t.distance.is_a?(Numeric) ? t.distance : 5 }.to_f / 12
      vec << (corp.share_price&.price.to_f / 400)
      vec << (corp.floated? ? 1.0 : 0.0)
      vec << (corp.owner == actor ? 1.0 : 0.0)
      vec << corp.tokens.count(&:used).to_f / 5
    end
    game.players.first(5).each do |player|
      vec << player.cash.to_f / 600
      vec << game.player_value(player).to_f / 4000
      vec << game.num_certs(player).to_f / 14
      vec << player.companies.size.to_f / 4
    end
    colors = game.hexes.map { |h| h.tile.color }
    %i[yellow green brown gray].each { |c| vec << colors.count(c).to_f / 76 }
    vec << game.tiles.size.to_f / 120
    vec << game.depot.upcoming.size.to_f / 12
    vec << (game.depot.min_depot_price.to_f / 900)
    touched = game.corporations.select { |c| c.owner == actor && c.tokens.any?(&:used) }
    vec << touched.size.to_f / 4
    vec << (entity.corporation? ? 1.0 : 0.0)
    vec = vec.first(STATE_SIZE)
    vec += Array.new(STATE_SIZE - vec.size, 0.0) if vec.size < STATE_SIZE
    vec
  end

  def hex_features(game, hex, entity)
    tile = hex.tile
    values = []
    HEX_COLORS.first(6).each { |c| values << (tile.color.to_s == c ? 1.0 : 0.0) }
    cities = tile.cities
    values << cities.sum { |c| c.max_revenue }.to_f / 120
    values << cities.size.to_f / 4
    values << cities.sum { |c| c.available_slots }.to_f / 4
    values << cities.sum { |c| c.tokens.compact.count { |t| t.corporation != entity } }.to_f / 4
    values << (tile.offboards.map(&:max_revenue).max.to_f / 120)
    values << (tile.icons.sum { |i| i.name.to_i }.to_f / 60)
    values << (tile.borders.sum { |b| b.cost.to_i }.to_f / 120)
    values << (hex.tile.color != :white ? 1.0 : 0.0)
    values << tile.exits.size.to_f / 6
    connected = begin
      game.graph_for_entity(entity).connected_hexes(entity)[hex] ? 1.0 : 0.0
    rescue StandardError
      0.0
    end
    values << connected
    values
  end

  def action_features(game, candidate, entity)
    info = candidate[:info] || {}
    type = candidate[:type].to_s
    vec = []
    TYPES.each { |t| vec << (t == type ? 1.0 : 0.0) }
    vec << (candidate[:cost].to_f / 900)
    vec << (candidate[:revenue].to_f / 600)
    hex = info[:hex] ? game.hex_by_id(info[:hex]) : nil
    if hex
      vec.concat(hex_features(game, hex, entity))
    else
      vec += Array.new(11, 0.0)
    end
    train = info[:train] ? game.depot.trains.find { |t| t.name == info[:train] } : nil
    vec << (train&.price.to_f || 0) / 900
    vec << (train&.distance.is_a?(Numeric) ? train.distance.to_f / 8 : 0.0)
    DIVIDENDS.each { |k| vec << (info[:kind] == k ? 1.0 : 0.0) }
    vec << (info[:par].to_f / 150)
    vec << (info[:percent].to_f / 30)
    vec = vec.first(ACTION_SIZE)
    vec += Array.new(ACTION_SIZE - vec.size, 0.0) while vec.size < ACTION_SIZE
    vec
  end

  def certs_of(game, player)
    game.num_certs(player)
  end
end
module P1846
  # Client for the local inference server (train/nnserver.py).
  class NeuralClient
    def initialize(url)
      @uri = URI(url)
      @http = Net::HTTP.new(@uri.host, @uri.port)
      @http.open_timeout = 1
      @http.read_timeout = 10
      @http.start
    end

    def scores(state, actions)
      request = Net::HTTP::Post.new(@uri.path, 'Content-Type' => 'application/json')
      request.body = JSON.generate(state: state, actions: actions)
      response = @http.request(request)
      raise "net HTTP #{response.code}" unless response.code == '200'

      JSON.parse(response.body).fetch('scores')
    end
  end
end
