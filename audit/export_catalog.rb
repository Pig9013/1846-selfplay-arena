# frozen_string_literal: true
# Export the tile/hex catalogue used by the log auditor.
require_relative '../engine_boot'
require 'json'

g = Engine::Game::G1846::Game.new({ '1' => 'A', '2' => 'B', '3' => 'C' }, id: '1846x', seed: 1)
build = lambda do |tile|
  {
    color: tile.color.to_s,
    cities: tile.cities.map { |c| { revenue: c.revenue.transform_keys(&:to_s), slots: c.normal_slots } },
    towns: tile.towns.map { |t| { revenue: t.revenue.transform_keys(&:to_s) } },
    offboards: tile.offboards.map do |o|
      { revenue: o.revenue.transform_keys(&:to_s), label: tile.label&.to_s, groups: o.groups }
    end,
    icons: tile.icons.map { |i| i.name.to_s },
    label: tile.label&.to_s,
  }
end
tiles = {}
(g.tiles + g.hexes.map(&:tile)).uniq(&:name).each { |tile| tiles[tile.name] = build.call(tile) }
hexes = g.hexes.to_h do |h|
  [h.id, { tile: h.tile.name, color: h.tile.color.to_s, location: h.location_name,
           label: h.tile.label&.to_s, groups: h.tile.offboards.flat_map(&:groups) }]
end
File.write(File.expand_path('catalog.json', __dir__), JSON.generate(tiles: tiles, hexes: hexes))
puts JSON.generate(tiles: tiles.size, hexes: hexes.size)