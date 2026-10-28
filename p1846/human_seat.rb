# frozen_string_literal: true

require 'json'
require 'fileutils'
require_relative '../arena'

# Interactive human seat for 1846. The human chooses among the same legal
# candidates the bots see; every choice is written as a state/action sample so
# it can be used for behaviour cloning later.
#
#   ruby p1846/human_seat.rb human-seat.json
#
# human-seat.json:
#   {"players":4,"seed":123,"human_seat":"1",
#    "strategies":["human","balanced","growth","income"],
#    "out":"train/human_data","net_url":"http://127.0.0.1:18346/scores"}
module P1846
  module HumanSeat
    module_function

    def player_of(entity)
      return entity if entity&.player?

      entity&.player
    end

    def show(game, entity, list)
      puts
      puts "=== #{game.round.name} / phase #{game.phase.name} / #{entity.id} ==="
      if entity.corporation?
        trains = entity.trains.map(&:name).join(',')
        puts "现金 $#{entity.cash}  列车 [#{trains}]  车站 #{entity.tokens.count(&:used)}"
      end
      limit = [list.size, 24].min
      limit.times do |i|
        c = list[i]
        detail = c[:info].is_a?(Hash) ? c[:info].slice(:hex, :tile, :city, :kind, :corp, :par, :company, :train) : {}
        puts format('%2d. %-14s %7.1f  %s %s', i, c[:type], c[:score].to_f,
                    c[:reason].to_s[0, 42], detail.to_json)
      end
      puts "共 #{list.size} 个候选；回车=最高分，q=退出"
    end

    def run(config)
      human_seat = config.fetch('human_seat', '1').to_s
      out = config.fetch('out', 'train/human_data')
      FileUtils.mkdir_p(out)
      bot = Arena1846::Bot.new(config)
      samples = []
      guard = 0
      until bot.game.finished
        guard += 1
        raise 'action guard' if guard > 4000

        step = bot.game.round.active_step
        entity = step.current_entity
        raise "no entity at #{step.class}" unless entity

        list = bot.candidates
        if list.empty?
          bot.advance
          next
        end
        player = player_of(entity)
        if player&.id.to_s == human_seat
          show(bot.game, entity, list)
          answer = $stdin.gets
          abort 'quit' if answer.nil? || answer.strip.downcase == 'q'

          choice = answer.strip.empty? ? 0 : answer.to_i
          choice = 0 unless choice.between?(0, list.size - 1)
          state = P1846.state_features(bot.game, entity)
          actions = list.take(12).map { |c| P1846.action_features(bot.game, c, entity) }
          begin
            bot.execute(list[choice])
            samples << { actor: player.id.to_s, state: state, actions: actions,
                         chosen: choice, prior: list.take(12).map { |c| c[:score].round(3) } }
          rescue StandardError => error
            puts "引擎拒绝：#{error.message}"
            bot.advance
          end
        else
          begin
            bot.execute(list.first)
          rescue StandardError
            bot.advance
          end
        end
      end
      scores = bot.game.result.transform_values(&:to_f)
      mean = scores.values.sum / [scores.size, 1].max
      var = scores.values.sum { |v| (v - mean)**2 } / [scores.size, 1].max
      std = Math.sqrt(var).clamp(1.0, Float::INFINITY)
      z = scores.transform_values { |v| ((v - mean) / std).clamp(-2.0, 2.0) }
      id = format('%s-human-%s', config.fetch('seed', 0), human_seat)
      File.open(File.join(out, "#{id}.jsonl"), 'w') do |file|
        file.puts JSON.generate(type: 'meta', seed: config.fetch('seed', 0),
                                players: config.fetch('players', 4), human_seat: human_seat,
                                feature_version: P1846::FEATURE_VERSION, degenerate: false,
                                low_quality: false, end_reason: bot.game.game_end_reason.to_s)
        samples.each do |sample|
          file.puts JSON.generate(type: 'decision', actor: sample[:actor],
                                  state: sample[:state].map { |v| v.round(4) },
                                  actions: sample[:actions].map { |a| a.map { |v| v.round(4) } },
                                  chosen: sample[:chosen], prior: sample[:prior])
        end
        file.puts JSON.generate(type: 'result', scores: scores, z: z,
                                winner: scores.max_by { |_, v| v }&.first,
                                margin: 0, winner_weight: 1)
      end
      puts JSON.generate(id: id, samples: samples.size, scores: scores)
      puts "saved to #{File.join(out, "#{id}.jsonl")}"
    end
  end
end

if $PROGRAM_NAME == __FILE__
  config = JSON.parse(File.read(ARGV[0], encoding: 'UTF-8'))
  P1846::HumanSeat.run(config)
end
