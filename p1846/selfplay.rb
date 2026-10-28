# frozen_string_literal: true

# One self-play game per process. Uses the same legal candidate generator and
# heuristic priors as the web platform, ranks candidates with the trained
# network when a network URL is configured, samples an action, and writes the
# decision samples for training.
require_relative '../arena'
require 'fileutils'

module SelfPlay
  module_function

  def softmax_sample(list, temperature, rng, limit: 12, epsilon: 0.05)
    pool = list.take(limit)
    return 0 if pool.size <= 1
    return rng.rand(pool.size) if rng.rand < epsilon

    scores = pool.map { |c| c[:score].to_f }
    top = scores.max
    mean = scores.sum / scores.size
    variance = scores.sum { |score| (score - mean)**2 } / scores.size
    # Temperature is expressed in standard deviations of this decision's
    # candidate scores, not in raw heuristic points. Raw points made a 600-point
    # net bonus effectively deterministic; sigma-scaling keeps exploration alive
    # whatever the scale of the current policy.
    sigma = Math.sqrt(variance).clamp(1.0, 250.0)
    scale = [temperature.to_f, 0.05].max * sigma
    weights = scores.map { |score| Math.exp((score - top) / scale) }
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
    progress = 0
    consecutive_pass = 0
    started = Time.now
    until bot.game.finished
      guard += 1
      raise 'action guard' if guard > 4000

      step = bot.game.round.active_step
      entity = step.current_entity
      raise "no entity at #{step.class}" unless entity

      list = bot.candidates
      raise "no candidates at #{step.class}" if list.empty?

      player = entity.player? ? entity : entity.player
      state = P1846.state_features(bot.game, entity)
      acts = list.take(12).map { |c| P1846.action_features(bot.game, c, entity) }
      idx = softmax_sample(list, config.fetch('temperature', 1.5).to_f, rng)
      choice = list[idx]
      kind = (choice[:type] || choice[:action]['type']).to_s
      if kind == 'pass'
        consecutive_pass += 1
      else
        consecutive_pass = 0
        progress += 1
      end
      # A healthy game reaches par/track within the first few dozen decisions.
      # Bailing out early stops a poisoned checkpoint from writing ten thousand
      # useless "pass" samples before the bank finally runs dry.
      raise 'degenerate pass loop' if consecutive_pass > 120
      raise 'no progress in draft/stock round' if guard > 120 && progress.zero?

      begin
        bot.execute(choice)
      rescue StandardError
        # A rejected candidate teaches nothing; play the engine-safe choice and
        # do not append a mislabelled training sample.
        bot.advance
        next
      end
      samples << { actor: player&.id, state: state, actions: acts, chosen: idx,
                   prior: list.take(12).map { |c| (c[:prior] || c[:score]).round(3) } }
    end
    result = bot.game.result
    scores = result.transform_values(&:to_f)
    mean = scores.values.sum / [scores.size, 1].max
    var = scores.values.sum { |v| (v - mean)**2 } / [scores.size, 1].max
    std = Math.sqrt(var).clamp(1.0, Float::INFINITY)
    z = scores.transform_values { |v| ((v - mean) / std).clamp(-2.0, 2.0) }
    actions = bot.game.raw_actions
    non_pass = actions.count { |action| action['type'] != 'pass' }
    degenerate = non_pass < 30 || actions.none? { |action| action['type'] == 'lay_tile' } ||
                 actions.none? { |action| action['type'] == 'par' }
    {
      samples: samples,
      scores: scores,
      z: z,
      end_reason: bot.game.game_end_reason,
      actions: actions,
      players: bot.config['players'],
      seed: bot.config['seed'],
      game: bot.config['game'],
      non_pass: non_pass,
      degenerate: degenerate,
      elapsed: (Time.now - started).round(2),
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
                            end_reason: data[:end_reason].to_s, feature_version: P1846::FEATURE_VERSION,
                            non_pass: data[:non_pass], degenerate: data[:degenerate], elapsed: data[:elapsed]))
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
                     non_pass: data[:non_pass], degenerate: data[:degenerate], elapsed: data[:elapsed],
                     scores: data[:scores], z: data[:z])
end