# frozen_string_literal: true

require 'json'
require 'socket'
require 'fileutils'
require_relative '../arena'

# Tiny local HTTP bridge for the "human vs 2 AI" window.
# GET  /state   -> game + candidates for the human seat
# POST /choose  {"index": N} -> execute that candidate, then let the AI seats move
# GET  /health
module P1846
  module HumanHTTP
    module_function

    def player_of(entity)
      return entity if entity&.player?

      entity&.player
    end

    class Session
      attr_reader :bot, :human_seat, :samples

      def initialize(config)
        @human_seat = config.fetch('human_seat', '1').to_s
        @bot = Arena1846::Bot.new(config)
        @samples = []
        @finished = false
        @saved = false
        @out = config.fetch('out', 'train/human_data')
        @seed = config.fetch('seed', 0)
        advance_ai
      end

      def player
        P1846::HumanHTTP.player_of(@bot.game.round.active_step.current_entity)
      end

      def human_turn?
        !@finished && player&.id.to_s == @human_seat
      end

      def advance_ai
        guard = 0
        until @bot.game.finished
          guard += 1
          raise 'action guard' if guard > 5000

          list = @bot.candidates
          if list.empty?
            @bot.advance
            next
          end
          break if human_turn?

          begin
            @bot.execute(list.first)
          rescue StandardError
            @bot.advance
          end
        end
        finish if @bot.game.finished
      end

      def finish
        return if @finished

        @finished = true
        save_samples
      end

      def save_samples
        return if @saved

        @saved = true
        FileUtils.mkdir_p(@out)
        scores = @bot.game.result.transform_values(&:to_f)
        mean = scores.values.sum / [scores.size, 1].max
        var = scores.values.sum { |v| (v - mean)**2 } / [scores.size, 1].max
        std = Math.sqrt(var).clamp(1.0, Float::INFINITY)
        z = scores.transform_values { |v| ((v - mean) / std).clamp(-2.0, 2.0) }
        id = format('%s-human-http-%s', @seed, @human_seat)
        File.open(File.join(@out, "#{id}.jsonl"), 'w') do |file|
          file.puts JSON.generate(type: 'meta', seed: @seed, players: @bot.config.fetch('players', 3),
                                  human_seat: @human_seat, feature_version: P1846::FEATURE_VERSION,
                                  degenerate: false, low_quality: false,
                                  end_reason: @bot.game.game_end_reason.to_s)
          @samples.each do |sample|
            file.puts JSON.generate(type: 'decision', actor: sample[:actor],
                                    state: sample[:state].map { |v| v.round(4) },
                                    actions: sample[:actions].map { |a| a.map { |v| v.round(4) } },
                                    chosen: sample[:chosen], prior: sample[:prior])
          end
          file.puts JSON.generate(type: 'result', scores: scores, z: z,
                                  winner: scores.max_by { |_, v| v }&.first,
                                  margin: 0, winner_weight: 1)
        end
      end

      def snapshot
        g = @bot.game
        entity = g.round.active_step.current_entity
        candidates = []
        if human_turn?
          list = @bot.candidates
          list.take(12).each_with_index do |candidate, index|
            info = candidate[:info].is_a?(Hash) ? candidate[:info].slice(:hex, :tile, :city, :kind, :corp, :par, :company, :train) : {}
            candidates << { index: index, type: candidate[:type], score: candidate[:score].to_f.round(2),
                            reason: candidate[:reason].to_s, info: info }
          end
        end
        {
          finished: @finished, human_turn: human_turn?, round: g.round.name,
          phase: g.phase.name, entity: entity&.id, cash: entity&.cash,
          trains: entity.respond_to?(:trains) ? entity.trains.map(&:name) : [],
          players: g.players.map { |p| { id: p.id, name: p.name, cash: p.cash,
                                         companies: g.corporations.select { |c| c.owner == p }.map(&:id) } },
          result: @finished ? g.result : nil,
          candidates: candidates
        }.to_json
      end

      def choose(index)
        raise 'not human turn' unless human_turn?

        list = @bot.candidates
        index = index.to_i
        raise 'bad index' unless index.between?(0, [list.size, 12].min - 1)

        entity = @bot.game.round.active_step.current_entity
        player = P1846::HumanHTTP.player_of(entity)
        state = P1846.state_features(@bot.game, entity)
        actions = list.take(12).map { |c| P1846.action_features(@bot.game, c, entity) }
        prior = list.take(12).map { |c| c[:score].round(3) }
        @bot.execute(list[index])
        @samples << { actor: player.id.to_s, state: state, actions: actions,
                      chosen: index, prior: prior }
        advance_ai
        { ok: true, snapshot: JSON.parse(snapshot) }.to_json
      rescue StandardError => error
        { ok: false, error: error.message, snapshot: JSON.parse(snapshot) }.to_json
      end
    end

    def serve(config)
      session = Session.new(config)
      port = Integer(config.fetch('port', 1847))
      server = TCPServer.new('127.0.0.1', port)
      puts "human-http listening on #{port}" 
      loop do
        client = server.accept
        begin
          request_line = client.gets.to_s.strip
          method, path, _ = request_line.split(' ')
          headers = {}
          while (line = client.gets) && line != "\r\n"
            key, value = line.split(':', 2)
            headers[key.downcase] = value.to_s.strip if key
          end
          body = headers['content-length'] ? client.read(headers['content-length'].to_i) : ''
          status, payload = if method == 'GET' && path == '/health'
                              [200, { ok: true, human_turn: session.human_turn? }.to_json]
                            elsif method == 'GET' && path == '/state'
                              [200, session.snapshot]
                            elsif method == 'POST' && path == '/choose'
                              index = JSON.parse(body).fetch('index', 0)
                              [200, session.choose(index)]
                            else
                              [404, { error: 'not found' }.to_json]
                            end
          client.write "HTTP/1.1 #{status} OK\r\nContent-Type: application/json; charset=utf-8\r\n" \
                       "Access-Control-Allow-Origin: *\r\nContent-Length: #{payload.bytesize}\r\nConnection: close\r\n\r\n#{payload}"
        rescue StandardError => error
          payload = { ok: false, error: error.message }.to_json
          client.write "HTTP/1.1 500 Error\r\nContent-Type: application/json\r\nContent-Length: #{payload.bytesize}\r\nConnection: close\r\n\r\n#{payload}"
        ensure
          client.close
        end
      end
    end
  end
end

if $PROGRAM_NAME == __FILE__
  P1846::HumanHTTP.serve(JSON.parse(File.read(ARGV[0], encoding: 'UTF-8')))
end
