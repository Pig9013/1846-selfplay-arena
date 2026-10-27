# frozen_string_literal: true

# One self-play game per process. Uses the same legal candidate generator and
# heuristic priors as the web platform, ranks candidates with the trained
# network when a network URL is configured, samples an action, and writes the
# decision samples for training.
require_relative '../arena'
require 'fileutils'

module SelfPlay
  module_function

  def softmax_sample(list, temperature, rng, limit: 12)
    pool = list.take(limit)
    return 0 if pool.size <= 1

    top = pool.first[:score]
    weights = pool.map { |c| Math.exp((c[:score] - top) / [temperature, 1e-3].max) }
    total = weights.sum
    pick = rng.rand * total
    acc = 0.0
    pool.each_with_index do |_, i|
      acc += weights[i]
      return i if pick <= acc
    end
    pool.size - 1
  end

  def run(config)
    rng = Random.new(Integer(config.fetch('seed', 0)) * 7919 + Integer(config.fetch('game', 0)))
    bot = Arena1846::Bot.new(config)
    samples = []
    guard = 0
    until bot.game.finished
      guard += 1
      raise 'action guard' if guard > 4000

      step = bot.game.round.active_step
      entity = step.current_entity
      list = bot.candidates
      raise "no candidates at #{step.class}" if list.empty?

      player = entity.player? ? entity : entity.player
      state = P1846.state_features(bot.game, entity)
      acts = list.take(12).map { |c| P1846.action_features(bot.game, c, entity) }
      idx = softmax_sample(list, config.fetch('temperature', 18.0).to_f, rng)
      begin
        bot.execute(list[idx])
        samples << { actor: player&.id, state: state, actions: acts, chosen: idx,
                     prior: list.take(12).map { |c| c[:score].round(3) } }
      rescue StandardError
        # A rejected sample teaches nothing useful; play the safe choice instead.
        decision = bot.advance
        samples << { actor: player&.id, state: state,
                     actions: decision[:candidates].take(12).map { |c| P1846.action_features(bot.game, c, entity) },
                     chosen: 0, prior: [] }
      end
    end
    result = bot.game.result
    scores = result.transform_values(&:to_f)
    mean = scores.values.sum / [scores.size, 1].max
    var = scores.values.sum { |v| (v - mean)**2 } / [scores.size, 1].max
    std = Math.sqrt(var).clamp(1.0, Float::INFINITY)
    z = scores.transform_values { |v| ((v - mean) / std).clamp(-2.0, 2.0) }
    {
      samples: samples,
      scores: scores,
      z: z,
      end_reason: bot.game.game_end_reason,
      actions: bot.game.raw_actions,
      players: bot.config['players'],
      seed: bot.config['seed'],
      game: bot.config['game'],
    }
  end
end

if $PROGRAM_NAME == __FILE__
  config = JSON.parse(File.read(ARGV[0], encoding: 'UTF-8'))
  out = config.fetch('out')
  FileUtils.mkdir_p(out)
  begin
    data = SelfPlay.run(config)
  rescue StandardError => e
    File.open(File.join(out, 'failures.log'), 'a') do |file|
      file.puts JSON.generate(seed: config['seed'], game: config['game'], error: e.message,
                              backtrace: e.backtrace.take(3))
    end
    warn JSON.generate(seed: config['seed'], game: config['game'], error: e.message)
    exit 2
  end
  id = format('%s-%05d', config.fetch('seed'), config.fetch('game'))
  File.open(File.join(out, "#{id}.jsonl"), 'w') do |file|
    file.puts(JSON.generate(type: 'meta', players: data[:players], seed: data[:seed], game: data[:game],
                            end_reason: data[:end_reason].to_s))
    data[:samples].each do |sample|
      file.puts(JSON.generate(type: 'decision', actor: sample[:actor], state: sample[:state].map { |v| v.round(4) },
                              actions: sample[:actions].map { |a| a.map { |v| v.round(4) } },
                              chosen: sample[:chosen], prior: sample[:prior]))
    end
    file.puts(JSON.generate(type: 'result', scores: data[:scores], z: data[:z]))
  end
  File.write(File.join(out, "#{id}.game.json"),
             JSON.generate(id: "1846#{data[:seed]}", title: '1846', players: (1..data[:players]).map { |i| { id: i.to_s, name: "AI #{i}" } },
                           settings: { seed: data[:seed], optional_rules: [] }, actions: data[:actions],
                           status: 'finished', result: data[:scores]))
  puts JSON.generate(id: id, decisions: data[:samples].size, end_reason: data[:end_reason].to_s,
                     scores: data[:scores], z: data[:z])
end