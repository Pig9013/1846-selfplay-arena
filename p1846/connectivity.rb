# frozen_string_literal: true

# Track-level reasoning that the engine already knows but the heuristic policy
# previously ignored: which edges of a newly laid tile actually connect to the
# company's network, which of them face an offboard, and whether the tile joins
# the two. This is what turns "lay track somewhere near the offboard" into
# "complete the offboard connection".
module P1846
  module Connectivity
    CHICAGO = 'D6'
    CHICAGO_CONNECTIONS = 'C5'
    OFFBOARD_HEXES = %w[B8 B18 C5 C17 C21 D22 E23 F22 G21 H20 I1 I17 J10].freeze

    module_function

    # A path endpoint is either a hex edge (0..5) or a city/town/offboard node.
    def key(part)
      part.edge? ? [:edge, part.num] : [:part, part.object_id]
    end

    def find(parent, node)
      parent[node] ||= node
      parent[node] = find(parent, parent[node]) unless parent[node] == node
      parent[node]
    end

    def union(parent, a, b)
      ra = find(parent, a)
      rb = find(parent, b)
      parent[ra] = rb unless ra == rb
    end

    def hex_distance(a, b)
      ((a.x - b.x).abs + (a.y - b.y).abs) / 2
    end

    # True when the neighbour across +edge+ is an offboard whose own track
    # actually reaches that shared edge. Red hexes are not automatically
    # connected: the offboard tile has to have a path to the facing edge too.
    def offboard_edge?(hex, edge)
      neighbour = hex.neighbors[edge]
      return false unless neighbour

      inverse = hex.invert(edge)
      neighbour.tile.paths.any? do |path|
        path.offboard && path.edges.any? { |part| part.num == inverse }
      end
    end

    def offboard_groups(hex, edge)
      neighbour = hex.neighbors[edge]
      return [] unless neighbour

      inverse = hex.invert(edge)
      groups = []
      neighbour.tile.paths.each do |path|
        next unless path.offboard
        next unless path.edges.any? { |part| part.num == inverse }

        groups.concat(path.offboard.groups || [])
        groups << 'W' if neighbour.tile.label&.to_s == 'W'
      end
      groups.uniq
    end

    def offboard_revenue(hex, edge, game, train)
      neighbour = hex.neighbors[edge]
      return 0 unless neighbour

      inverse = hex.invert(edge)
      values = neighbour.tile.paths.filter_map do |path|
        next unless path.offboard
        next unless path.edges.any? { |part| part.num == inverse }

        path.offboard.route_revenue(game.phase, train)
      end
      values.max || 0
    end

    # Analyse one rotated tile at +hex+. +connected_edges+ is the hash returned
    # by the engine's tracker_available_hex for this hex before the lay.
    def analyze_tile(game, entity, hex, tile, connected_edges)
      parent = {}
      paths = tile.paths
      paths.each { |path| union(parent, key(path.a), key(path.b)) }

      edge_nums = paths.flat_map { |path| path.edges.map(&:num) }.uniq
      roots_edges = Hash.new { |hash, root| hash[root] = [] }
      edge_nums.each { |num| roots_edges[find(parent, [:edge, num])] << num }

      network_edges = if connected_edges.is_a?(Hash)
                        connected_edges.keys
                      else
                        Array(connected_edges)
                      end
      network_roots = network_edges.map { |num| find(parent, [:edge, num]) }
      # Tokens live on the OLD tile during an upgrade. Map old cities to their
      # new counterparts before asking "is this a network city?", otherwise a
      # D6 upgrade with GT's token in city 3 looks disconnected.
      city_map = begin
        hex.city_map_for(tile)
      rescue StandardError
        {}
      end
      city_map.each do |old_city, new_city|
        next unless new_city
        next unless old_city.tokened_by?(entity)

        network_roots << find(parent, [:part, new_city.object_id])
      end
      network_roots.compact!
      network_roots.uniq!

      offboard_edges = edge_nums.select { |num| offboard_edge?(hex, num) }
      offboard_roots = offboard_edges.map { |num| find(parent, [:edge, num]) }
      tile.offboards.each { |offboard| offboard_roots << find(parent, [:part, offboard.object_id]) }
      offboard_roots.compact!
      offboard_roots.uniq!

      link = (network_roots & offboard_roots).any?
      groups = offboard_edges.flat_map { |num| offboard_groups(hex, num) }.uniq
      train = game.route_trains(entity).first || P1846.display_train(game)
      offboard_value = if link
                         offboard_edges.map { |num| offboard_revenue(hex, num, game, train) }.max.to_i
                       else
                         0
                       end

      city_roots = (tile.cities + tile.towns).map { |node| find(parent, [:part, node.object_id]) }
      through_edges = roots_edges.select { |root, _| city_roots.include?(root) }
                                 .values.map(&:size).max || 0

      old_revenue = hex.tile.cities.sum { |city| city.route_revenue(game.phase, train) }
      new_revenue = tile.cities.sum { |city| city.route_revenue(game.phase, train) }

      chicago = game.hex_by_id(CHICAGO)
      distance = chicago ? hex_distance(hex, chicago) : 99
      {
        hex: hex.id,
        tile: tile.name,
        color: tile.color.to_s,
        upgrade: hex.tile.color != :white,
        connected_edges: network_edges.size,
        offboard_edges: offboard_edges.size,
        offboard_link: link,
        offboard_groups: groups,
        offboard_value: offboard_value,
        points_at_offboard: offboard_edges.any?,
        through_edges: through_edges,
        old_city_revenue: old_revenue.to_i,
        new_city_revenue: new_revenue.to_i,
        upgrade_gain: (new_revenue - old_revenue).to_i,
        chicago: hex.id == CHICAGO,
        chicago_upgrade: hex.id == CHICAGO && hex.tile.color != tile.color,
        chicago_gateway: hex.id == CHICAGO || hex.neighbors.values.any? { |n| [CHICAGO, CHICAGO_CONNECTIONS].include?(n.id) },
        distance_to_chicago: distance,
        offboard_adjacent: hex.neighbors.values.count { |n| n.tile.offboards.any? },
      }
    end
  end
end
