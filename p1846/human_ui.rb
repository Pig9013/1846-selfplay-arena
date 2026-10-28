# frozen_string_literal: true

# Human-facing projection of the rules engine: the action list, Chinese labels
# and the group names that web/human.html renders in its 18xx.games-style dock.
# Nothing here decides anything; it only describes engine state faithfully.
module P1846
  module HumanUI
    GROUP_LABELS = {
      'lay_tile' => '铺轨',
      'place_token' => '设置车站',
      'run_routes' => '营运',
      'dividend' => '分红',
      'buy_train' => '购买列车',
      'discard_train' => '淘汰列车',
      'buy_company' => '收购公司',
      'assign' => '指派私营',
      'bid' => '竞标私营',
      'par' => '开办公司',
      'buy_shares' => '买入股票',
      'sell_shares' => '卖出股票',
      'bankrupt' => '宣告破产',
      'pass' => '结束行动',
    }.freeze
    ORDER = %w[lay_tile place_token run_routes dividend buy_train discard_train buy_company
               assign bid par buy_shares sell_shares bankrupt pass].freeze
    DIVIDENDS = { 'withhold' => '留存收益', 'half' => '半额分红', 'payout' => '全额分红' }.freeze
    STEP_LABELS = {
      'DraftDistribution' => '私营公司分配',
      'Draft2pDistribution' => '私营公司分配',
      'BuySellParShares' => '股票轮 · 买卖股票与开办公司',
      'TrackAndToken' => '铺轨与设站',
      'SpecialTrack' => '特殊铺轨',
      'Track' => '铺轨',
      'Token' => '设置车站',
      'Route' => '营运 · 计算线路',
      'Dividend' => '分红决策',
      'BuyTrain' => '购买列车',
      'BuyCompany' => '收购私营公司',
      'Assign' => '指派私营公司',
      'IssueShares' => '公司增发股票',
      'Bankrupt' => '破产处理',
      'ReceivershipSkip' => '托管跳过',
    }.freeze
    MAX_PER_GROUP = 140

    # The seat the human plays; labels say "你" for their own holdings.
    class << self
      attr_accessor :human_seat
    end

    module_function

    def corporation(game, id)
      game.corporations.find { |c| c.id == id } || game.minors.find { |m| m.id == id }
    end

    def corp_name(game, id)
      corporation(game, id)&.name || id.to_s
    end

    def company_name(game, id)
      game.company_by_id(id)&.name || id.to_s
    end

    def step_label(step)
      return '' unless step

      STEP_LABELS[step.class.name.split('::').last.to_s] || (step.respond_to?(:description) ? step.description.to_s : '')
    end

    def hex_name(game, id)
      hex = game.hexes.find { |h| h.id == id.to_s }
      loc = hex&.location_name
      loc && !loc.empty? ? "#{hex.id} #{loc}" : id.to_s
    end

    # One short line a human can act on, plus a secondary line of context.
    def describe(candidate, game)
      info = candidate[:info] || {}
      action = candidate[:action] || {}
      type = candidate[:type].to_s
      cost = candidate[:cost]
      revenue = candidate[:revenue]
      case type
      when 'bid'
        company = company_name(game, info[:company])
        if info[:blank]
          number = company[/\d+/] || ''
          ["放弃购买私营公司#{number.empty? ? '' : "（Pass #{number}）"}", '打出弃权牌，本轮不买公司']
        else
          ["竞标 #{company} · $#{cost}", '出价最高者得到该公司']
        end
      when 'par'
        name = corp_name(game, info[:corp])
        par = info[:par] || cost.to_i / 2
        ["开办 #{name} · 股价 $#{par}", "支付 $#{cost}，拥有 20% 总裁股"]
      when 'buy_shares'
        name = corp_name(game, info[:corp])
        if info[:redeem]
          ["赎回 #{name} #{info[:percent]}% · $#{cost}", '公司金库买回自己的股票']
        else
          ["买入 #{name} #{info[:percent]}%#{(info[:president] ? '（总裁股）' : '')} · $#{cost}", '从公司或股票池买入']
        end
      when 'sell_shares'
        name = corp_name(game, info[:corp])
        percent = info[:percent] || action['percent']
        percent = Array(action['shares']).size * 10 if percent.nil?
        if info[:issue]
          ["增发 #{name} #{percent}% · 得 $#{revenue}", '公司金库向股票池增发']
        else
          ["卖出 #{name} #{percent}% · 得 $#{revenue}", '卖到股票池，可能压低股价']
        end
      when 'lay_tile'
        hex = hex_name(game, info[:hex] || action['hex'])
        tile = info[:tile] || action['tile'].to_s.split('-').first
        rotation = action['rotation'] || info[:rotation] || 0
        upgrade = info[:upgrade]
        [upgrade ? "升级 #{hex} → #{tile} 号瓦（转 #{rotation}）· $#{cost}" :
                   "铺轨 #{hex} · #{tile} 号瓦（转 #{rotation}）· $#{cost}",
         upgrade ? '把格子上的瓦换成更高一级' : '在空地上放第一块瓦']
      when 'place_token'
        extra = info[:reserved] ? '（保留位）' : (info[:teleport] ? '（特权传送）' : '')
        ["设置车站 #{hex_name(game, info[:hex])}#{extra}", "第 #{info[:city].to_i + 1} 个城市位 · $#{cost}"]
      when 'run_routes'
        count = info[:routes].is_a?(Integer) ? info[:routes] : Array(action['routes']).size
        ["营运 · 选定 #{count} 条线路 · 收入 $#{revenue}", info[:timed_out] ? '线路搜索超时，使用了当前最优解' : '确认后进入分红决策']
      when 'dividend'
        ["#{DIVIDENDS[info[:kind].to_s] || info[:kind]}", info[:kind].to_s == 'withhold' ? '收益进公司金库，股价左移' : '收益按股发放，股价右移']
      when 'buy_train'
        variant = info[:variant].to_s
        ["购买 #{info[:train]} 号车 · $#{cost}", "#{info[:first] ? '本局第一列' : '第 ' + info[:distance].to_s + ' 级'}#{variant.empty? || variant == '2' ? '' : ' · 变体 ' + variant}"]
      when 'discard_train'
        ["淘汰 #{info[:train]} 号车", '超过持有上限，必须弃一列']
      when 'buy_company'
        name = company_name(game, info[:company])
        company = game.company_by_id(info[:company])
        price = info[:price] || cost
        owner = company&.owner
        if owner
          owner_name = owner.id.to_s == HumanUI.human_seat.to_s ? '你' : owner.name
          prefix = owner_name == '你' ? "收购你的 #{name}" : "向 #{owner_name} 收购 #{name}"
          ["#{prefix} · $#{price}",
           "明面价值 $#{company.value}；$1 到明面价值之间都可以报价"]
        else
          ["收购 #{name} · $#{price}", '从银行买下私营公司']
        end
      when 'assign'
        target = info[:hex] ? "地块 #{hex_name(game, info[:hex])}" : "公司 #{corp_name(game, info[:corp])}"
        ["指派 #{company_name(game, info[:company])} → #{target}", '私营公司的能力指向这里']
      when 'bankrupt'
        ['宣告破产', '总裁无法凑齐列车费用']
      when 'pass'
        ['过', '本步不做动作，交给下一位']
      else
        [type, '']
      end
    end

    # Ghost tile for the hex preview: the exact glyph 1846 would place,
    # reconstructed from the action the engine already validated.
    def tile_preview_for(candidate, game)
      return nil unless candidate[:type].to_s == 'lay_tile'

      action = Engine::Action::Base.action_from_h(candidate[:action], game)
      P1846.tile_preview(game, action.tile, action.rotation)
    rescue StandardError
      nil
    end

    # Compact chip text for grouped lists (one chip per price/rotation/share).
    def short_label(type, info, action, game)
      case type
      when 'par' then info[:par] ? "$#{info[:par]}" : '开办'
      when 'buy_shares' then (info[:redeem] ? '赎回 ' : '') + "#{info[:percent]}%"
      when 'sell_shares' then "#{info[:percent]}%"
      when 'lay_tile'
        tile = info[:tile] || action['tile'].to_s.split('-').first
        rotation = action['rotation'] || info[:rotation] || 0
        (info[:upgrade] ? '升级 ' : '') + "#{tile}（转#{rotation}）"
      when 'place_token' then "城市位 #{info[:city].to_i + 1}"
      when 'dividend' then DIVIDENDS[info[:kind].to_s] || info[:kind].to_s
      when 'buy_train' then "#{info[:train]} 号车"
      when 'bid' then info[:blank] ? '放弃' : "$#{action['price'] || ''}"
      when 'buy_company' then "$#{info[:price] || 0}"
      when 'assign' then info[:hex] || info[:corp] || ''
      when 'pass' then '过'
      else ''
      end
    end

    def candidate_json(candidate, game, pick)
      label, sub = describe(candidate, game)
      info = candidate[:info] || {}
      action = candidate[:action] || {}
      entry = {
        pick: pick,
        type: candidate[:type].to_s,
        label: label,
        sub: sub,
        score: candidate[:score].to_f.round(2),
        cost: candidate[:cost],
        revenue: candidate[:revenue],
        hex: info[:hex] || action['hex'],
        corp: info[:corp] || action['corporation'],
        tile: info[:tile] || action['tile'].to_s.split('-').first,
        rotation: action['rotation'] || info[:rotation],
        company: info[:company],
        train: info[:train],
        kind: info[:kind],
        par: info[:par],
      }
      entry[:short] = short_label(entry[:type], info, action, game)
      entry[:entity] = action['entity']
      entry[:owner] = game.company_by_id(info[:company])&.owner&.id if info[:company]
      preview = tile_preview_for(candidate, game)
      entry[:preview] = preview if preview
      entry
    end

    def dedup_key(entry)
      case entry[:type]
      when 'buy_shares'
        [:buy, entry[:corp], entry[:label]]
      when 'sell_shares'
        [:sell, entry[:corp], entry[:label]]
      else
        nil
      end
    end

    # Raw candidates -> display entries with stable pick indices, de-duplicated
    # by economic meaning (1846 hands out one certificate per share, so a plain
    # "buy 10% IC" would otherwise appear eight times).
    def project(list, game, skip: nil)
      seen = {}
      entries = []
      list.each_with_index do |candidate, index|
        next if skip&.call(candidate)

        entry = candidate_json(candidate, game, index)
        key = dedup_key(entry)
        if key
          next if seen[key]

          seen[key] = true
        end
        entries << entry
      end
      entries.sort_by! { |e| [ORDER.index(e[:type]) || 99, -e[:score].to_f] }
      counts = entries.group_by { |e| e[:type] }.transform_values(&:size)
      kept = []
      per_group = Hash.new(0)
      entries.each do |entry|
        next if per_group[entry[:type]] >= MAX_PER_GROUP

        per_group[entry[:type]] += 1
        kept << entry
      end
      groups = ORDER.filter_map do |type|
        next unless counts[type]

        { type: type, label: GROUP_LABELS[type], count: counts[type] }
      end
      { groups: groups, candidates: kept }
    end
  end
end
