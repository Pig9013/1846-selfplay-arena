# frozen_string_literal: true
# Replay every action with normal validation; never trust serialized route income.
require_relative 'engine_boot'

document = JSON.parse(File.read(ARGV.fetch(0), encoding: 'UTF-8'))
names = document.fetch('players').to_h { |p| [p.fetch('id').to_s, p.fetch('name')] }
game = Engine::Game::G1846::Game.new(names, id: document.fetch('id'), seed: document.dig('settings', 'seed'))
entities = [game.bank, *game.players, *game.corporations, *game.minors]
cash = -> { entities.sum(&:cash) }
initial_cash = cash.call
routes_checked = 0
document.fetch('actions').each do |hash|
  raise 'Manual end/undo not allowed in self-play verification' if %w[end_game undo redo].include?(hash['type'])
  action = Engine::Action::Base.action_from_h(hash, game)
  if action.is_a?(Engine::Action::RunRoutes)
    action.routes.each(&:clear_cache!)
    action.routes.each do |route|
      revenue = route.revenue
      serialized = hash.fetch('routes').find { |r| r['train'] == route.train.id }
      raise "Revenue mismatch at action #{hash['id']}" if serialized['revenue'] && revenue != serialized['revenue']
      routes_checked += 1
    end
  end
  game.process_action(action, add_auto_actions: true).maybe_raise!
  raise "Cash not conserved at action #{hash['id']}: #{cash.call} != #{initial_cash}" unless cash.call == initial_cash
end
raise 'Not a natural completed game' unless game.finished && game.game_end_reason != :dnf
raise 'Final result mismatch' unless game.result == document.fetch('result')
puts JSON.generate(verified: true, actions: game.current_action_id, routes_checked: routes_checked,
                   end_reason: game.game_end_reason, result: game.result, total_cash: initial_cash)
