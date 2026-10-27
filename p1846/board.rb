# frozen_string_literal: true

# Rich, rules-faithful 1846 state export used by the web UI, the bots and the
# learning pipeline. Everything here is derived from the upstream engine; no
# value is invented.
module P1846
  COLORS = %w[white yellow green brown gray red blue].freeze

  module_function

  def display_train(game)
    game.depot&.upcoming&.first || game.trains.first
  end

  def revenue_of(center, game, train = nil)
    train ||= display_train(game)
    center.route_revenue(game.phase, train)
  end

  # Tile cost charged by the engine for laying +tile+ on +hex+:
  # max(20, printed terrain) + every hexside cost that the new track completes,
  # then minus the company's discounts (IC land grants, Tunnel Blasting).
  def tile_cost(game, entity, hex, tile)
    old = hex.tile
    cost = [20, old.upgrades.sum(&:cost)].max
    borders = 0
    tile.borders.each do |border|
      next unless border.cost

      neighbor = hex.neighbors[border.edge]
      next unless neighbor
      next unless hex.targeting?(neighbor) && neighbor.targeting?(hex)

      borders += border.cost
    end
    cost += borders
    if entity
      game.abilities(entity, :tile_lay) do |ability|
        next if ability.hexes.any? && !ability.hexes.include?(hex.id)

        cost -= ability.discount if ability.discount
      end
      game.abilities(entity, :tile_discount) do |ability|
        next if ability.terrain && ability.terrain != :mountain

        cost -= ability.discount if ability.discount
      end
    end
    [cost, 0].max
  end

  def endpoint(part)
    if part.edge?
      { edge: part.num }
    else
      kind = if part.city?
               'city'
             elsif part.offboard?
               'offboard'
             elsif part.town?
               'town'
             else
               'node'
             end
      { node: part.index, kind: kind }
    end
  end

  def groups_of(node)
    node.respond_to?(:groups) ? node.groups : []
  end

  def icon_bonus(tile)
    tile.icons.sum { |icon| icon.name.to_i }
  end

  def city_json(city, game, train, tile = nil)
    edges = []
    tile&.paths&.each do |path|
      pair = [path.a, path.b]
      next unless pair.include?(city)

      other = (pair - [city]).first
      edges << other.num if other&.edge?
    end
    anchor = edges.size == 1 ? edges.first : nil
    {
      index: city.index,
      anchor: anchor,
      revenue: revenue_of(city, game, train),
      slots: city.normal_slots,
      tokens: city.tokens.compact.map do |token|
        { id: token.corporation.id, color: token.corporation.color.to_s, type: token.type.to_s }
      end,
      reserved: city.reservations.compact.map { |r| r.respond_to?(:id) ? r.id : r.to_s },
      groups: city.groups,
      blocked_by: game.corporations.select { |c| city.blocks?(c) }.map(&:id),
    }
  end

  def offboard_json(offboard, game, train, tile)
    {
      index: offboard.index,
      revenue: revenue_of(offboard, game, train),
      groups: offboard.groups,
      bonus: tile.icons.sum { |icon| icon.name.to_i },
      label: tile.label&.to_s,
      hide: offboard.hide ? true : false,
    }
  end

  def hex_json(hex, game, train)
    tile = hex.tile
    cities = tile.cities.map { |c| city_json(c, game, train, tile) }
    offboards = tile.offboards.map { |o| offboard_json(o, game, train, tile) }
    terrain = tile.upgrades.sum(&:cost)
    borders = tile.borders.map do |border|
      neighbor = hex.neighbors[border.edge]
      connected = neighbor ? (hex.targeting?(neighbor) && neighbor.targeting?(hex)) : false
      { edge: border.edge, type: border.type.to_s, cost: border.cost, crossed: connected }
    end
    {
      id: hex.id, x: hex.x, y: hex.y, col: hex.column, row: hex.row,
      location: hex.location_name, color: tile.color.to_s, tile: tile.name,
      label: tile.label&.to_s,
      exits: tile.exits,
      terrain: terrain,
      cost: [20, terrain].max,
      borders: borders,
      cities: cities,
      offboards: offboards,
      towns: tile.towns.map { |t| { index: t.index, revenue: revenue_of(t, game, train) } },
      paths: tile.paths.map { |path| [endpoint(path.a), endpoint(path.b)] },
      icons: tile.icons.map { |icon| icon.name.to_s },
      bonus: icon_bonus(tile),
      east: tile.offboards.any? { |o| o.groups.include?('E') },
      west: tile.label&.to_s == 'W' || tile.offboards.any? { |o| o.groups.include?('W') },
      assignments: hex.assignments.keys,
      blocked: cities.any? { |c| c[:blocked_by].any? },
      hidden: offboards.any? && offboards.all? { |o| o[:hide] },
    }
  end

  def tile_stock(game)
    game.tiles.group_by(&:name).map do |name, list|
      tile = list.first
      {
        name: name, color: tile.color.to_s, count: tile.unlimited ? 99 : list.size,
        unlimited: tile.unlimited,
        cities: tile.cities.size, towns: tile.towns.size, exits: tile.exits.size,
        max_revenue: tile.nodes.map(&:max_revenue).max || 0,
      }
    end.sort_by { |h| [COLORS.index(h[:color]) || 9, h[:name].to_i] }
  end

  def board(game)
    train = display_train(game)
    {
      phase: game.phase.name,
      train: train&.name,
      phase_tiles: game.phase.tiles.map(&:to_s),
      hexes: game.hexes.map { |hex| hex_json(hex, game, train) },
      tile_stock: tile_stock(game),
      tile_lays: game.corporations.select(&:floated?).to_h do |corp|
        lay = game.tile_lays(corp)
        [corp.id, lay.map { |l| { lay: l[:lay], upgrade: l[:upgrade], cost: l[:cost] } }]
      end,
    }
  end
end