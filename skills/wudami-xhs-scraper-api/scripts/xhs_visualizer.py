#!/usr/bin/env python3
"""
小红书账号拆解报告 - 可视化生成器
将 AI 输出的 Markdown 报告与基础分析产生的 JSON 数据结合，
生成一份带动态维度词频和可视化图表的 HTML 交互式简报。
"""

import json
import re
import os
import argparse

import urllib.parse

def generate_visual_html(md_path, json_path, output_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        analyzer_data = json.load(f)
        
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    # 从 analyzer 输出的数据集提取必要的元数据
    wc_data = analyzer_data.get('wordcloud', {})
    stats_fans = analyzer_data['account'].get('fansCount', '0')
    if isinstance(stats_fans, int) and stats_fans > 10000:
        stats_fans = f"{stats_fans/10000:.1f}万"
    stats_notes = analyzer_data['stats'].get('totalNotes', 0)
    engagement_rate = analyzer_data.get('engagementRate', 0)
    vr = analyzer_data.get('contentType', {}).get('videoRatio', 0)
    video_ratio_str = f"{vr*100:.0f}%" if vr else "0%"
    engagement_str = f"{engagement_rate}%" if engagement_rate else "未知"
    
    notes = analyzer_data.get('notes', [])

    html_output = ''
    lines = md_text.split('\n')
    in_table = False
    processed_titles = set()
    current_h2 = ''

    def build_dashboard():
        return f'''
        <div class="dashboard">
            <div class="stat-card"><div class="stat-value">{stats_fans}</div><div class="stat-label">总粉丝数</div></div>
            <div class="stat-card"><div class="stat-value">{stats_notes}</div><div class="stat-label">分析样本</div></div>
            <div class="stat-card highlight"><div class="stat-value">{engagement_str}</div><div class="stat-label">估算互动率</div></div>
            <div class="stat-card"><div class="stat-value">{video_ratio_str}</div><div class="stat-label">视频占比</div></div>
        </div>
        '''

    def build_gallery():
        if not notes: return ""
        html = '<div class="gallery-scroll">'
        for i, n in enumerate(notes[:8]):
            cover = n.get("cover", "")
            if cover: cover = cover.replace("/format/heif/", "/format/webp/")
            note_url = n.get("noteUrl", "") or n.get("note_url", "")
            
            # 【核心优化】如果没有 xsec_token 护照，直连会被拦截墙拦截。采用官方搜索跳板绕过。
            if note_url and "xsec_token=" not in note_url and n.get("title"):
                note_url = f"https://www.xiaohongshu.com/search_result/?keyword={urllib.parse.quote(n['title'])}&source=web_search_result"
                
            # Fallback 占位图
            if not cover: cover = "data:image/svg+xml;charset=UTF-8,%3Csvg%20width%3D%22200%22%20height%3D%22260%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%20200%20260%22%20preserveAspectRatio%3D%22none%22%3E%3Cdefs%3E%3Cstyle%20type%3D%22text%2Fcss%22%3E%23holder_18e5907406a%20text%20%7B%20fill%3A%23999%3Bfont-weight%3Anormal%3Bfont-family%3Avar(--bs-font-sans-serif)%2C%20sans-serif%3Bfont-size%3A13pt%20%7D%20%3C%2Fstyle%3E%3C%2Fdefs%3E%3Cg%20id%3D%22holder_18e5907406a%22%3E%3Crect%20width%3D%22200%22%20height%3D%22260%22%20fill%3D%22%23eee%22%3E%3C%2Frect%3E%3Cg%3E%3Ctext%20x%3D%2269.5390625%22%20y%3D%22136.2%22%3ENo%20Image%3C%2Ftext%3E%3C%2Fg%3E%3C%2Fg%3E%3C%2Fsvg%3E"
            
            # 如果有笔记链接，整张卡片可点击跳转
            card_open  = f'<a class="gallery-card-link" href="{note_url}" target="_blank" title="点击查看原笔记">' if note_url else '<div class="gallery-card">'
            card_close = '</a>' if note_url else '</div>'
            link_hint  = '<div class="link-hint">🔗 点击查看</div>' if note_url else ''
            
            html += f'''
            {card_open}
                <div class="rank-badge">TOP {i+1}</div>
                <img src="{cover}" alt="cover">
                <div class="gallery-info">
                    <div class="g-title">{n["title"]}</div>
                    <div class="g-likes">❤️ {n["likes"]}</div>
                    {link_hint}
                </div>
            {card_close}
            '''
        html += '</div>'
        return html

    def build_wordcloud():
        def gen_bubbles(words_list, sizes, palettes):
            if not words_list: return ''
            html = '<div class="wordcloud-sm">'
            for i, item in enumerate(words_list[:10]):
                bg = palettes[i % len(palettes)][0]
                fg = palettes[i % len(palettes)][1]
                sz = sizes[i] if i < len(sizes) else sizes[-1]
                html += f'<span class="bubble" style="font-size:{sz}em; background:{bg}; color:{fg};" title="{item["count"]}次">{item["word"]} <small style="opacity:0.5;font-size:0.6em;font-weight:normal;">{item["count"]}</small></span> '
            return html + '</div>'

        全局词 = wc_data.get('global_top', [])
        人群词 = wc_data.get('crowd', [])
        情绪词 = wc_data.get('emotion', [])
        动作词 = wc_data.get('action', [])
        场景词 = wc_data.get('scene', [])
        
        purple_p = [('#ede7f6', '#4527a0'), ('#d1c4e9', '#311b92')]
        red_p = [('#ffe0eb', '#d62828'), ('#ffcdd2', '#b71c1c')]
        blue_p = [('#e0f7fa', '#006064'), ('#b3e5fc', '#01579b')]
        green_p = [('#e8f5e9', '#1b5e20'), ('#c8e6c9', '#2e7d32')]
        orange_p = [('#fff3e0', '#e65100'), ('#ffe0b2', '#ef6c00')]
        sizes = [1.6, 1.4, 1.3, 1.1, 1.0, 0.9]

        wc_html = ''
        if 全局词: wc_html += '<div class="dim-label">🌟 全局高频词 TOP</div>' + gen_bubbles(全局词, sizes, purple_p)
        if 人群词: wc_html += '<div class="dim-label">👥 核心人群锁定</div>' + gen_bubbles(人群词, sizes, red_p)
        if 情绪词: wc_html += '<div class="dim-label">⚡ 情绪钩子设置</div>' + gen_bubbles(情绪词, sizes, blue_p)
        if 动作词: wc_html += '<div class="dim-label">🔨 动作指令引导</div>' + gen_bubbles(动作词, sizes, green_p)
        if 场景词: wc_html += '<div class="dim-label">🏠 场景需求覆盖</div>' + gen_bubbles(场景词, sizes, orange_p)

        return f'''
        <div class="visual-panel wordcloud-panel" style="margin-top: 20px;">
            <div class="panel-section">
                <div class="panel-title">🎯 独家五维词频抓取（NLP全量分词）</div>
                {wc_html}
            </div>
        </div>
        '''

    def build_donut_chart():
        # Parse dimensions from the AI's markdown output (section 七)
        # Look for lines like: **维度名**：N 篇（占比 X%）
        dim_pattern = re.compile(r'\*\*(.+?)\*\*[：:]\s*(\d+)\s*篇[（(]占比\s*(\d+)%[）)]')
        dimensions = []
        in_section7 = False
        for line in lines:
            if '选题维度' in line and (line.startswith('## ') or line.startswith('### ')):
                in_section7 = True
                continue
            if in_section7 and (line.startswith('## ') or line.startswith('### ')):
                break
            if in_section7:
                m = dim_pattern.search(line)
                if m:
                    dimensions.append({
                        'name': m.group(1),
                        'count': int(m.group(2)),
                        'ratio': int(m.group(3))
                    })

        if not dimensions: return ""

        total_p = 0
        gradient_stops = []
        chart_legend = ""
        colors = ["#e9ecef", "#ff2442", "#ff6b81", "#ff9eaa", "#ffc2c9", "#ffe0e4"]

        for i, dim in enumerate(dimensions[:6]):
            ratio = dim['ratio']
            name = dim['name']
            color = colors[i % len(colors)]

            p_start = total_p
            p_end = total_p + ratio
            gradient_stops.append(f"{color} {p_start}% {p_end}%")
            chart_legend += f'<div class="legend-item"><span class="color-box" style="background:{color};"></span>{name}({ratio}%)</div>\n'
            total_p = p_end

        if not gradient_stops: gradient_stops.append("#eee 0% 100%")
        conic = ", ".join(gradient_stops)

        return f'''
        <div class="visual-panel chart-panel" style="margin-top: 30px;">
            <div class="panel-section" style="flex:0.6;">
                <div class="panel-title">📊 内容维度分布</div>
                <div class="css-chart-container">
                    <div class="css-donut" style="background: conic-gradient({conic});"></div>
                    <div class="chart-legend">
                        {chart_legend}
                    </div>
                </div>
            </div>
        </div>
        '''

    for line_idx, line in enumerate(lines):
        if line.startswith('# '):
            html_output += f'<h1>{line[2:]}</h1>\n'
            html_output += build_dashboard()
            html_output += build_gallery()
        elif line.startswith('## ') or line.startswith('### '):
            is_h3 = line.startswith('### ')
            level = 3 if is_h3 else 2
            current_h2 = line[4:] if is_h3 else line[3:]
            html_output += f'<h{level} class="section-title">{current_h2}</h{level}>\n'
            
            # Inject donut chart right around topic breakdown
            if '选题维度' in current_h2:
                html_output += build_donut_chart()
                
        elif line.startswith('|') and '-|-' in line:
            pass 
        elif line.startswith('|'):
            cols = [c.strip() for c in line.split('|')[1:-1]]
            if '标题' in cols:
                html_output += '<table><tr><th>' + '</th><th>'.join(cols) + '</th></tr>\n'
                in_table = True
            else:
                if in_table:
                    html_output += '<tr><td>' + '</td><td>'.join(cols) + '</td></tr>\n'
                else:
                    html_output += '<table><tr><td>' + '</td><td>'.join(cols) + '</td></tr></table>\n'
        else:
            # === 拦截词云分析块，不生成多余的丑陋冗余文本 ===
            if '④ 词云分析' in line:
                html_output += build_wordcloud()
                continue
                
            if re.match(r'^\s*-\s*\*\*(全局高频词|人群词|情绪钩子词|动作指令词|场景.*?需求词).*?\*\*', line) or '以下数据由 Python jieba 分词精确计算' in line:
                continue

            if in_table:
                html_output += '</table>\n'
                in_table = False
                
            styled_line = line
            styled_line = re.sub(r'_(.*?)_', r'<em>\1</em>', styled_line)
            
            inject_html = ""
            
            # Fuzzy title matching logic for markdown embedding
            matches = re.finditer(r'(?<!>)(《([^》]+)》)(?!<)', styled_line)
            for match in matches:
                full_book_mark = match.group(1)
                ext_title = match.group(2).strip()
                if len(ext_title) < 2: continue
                
                best_note = None
                for t in notes:
                    if not t['title']: continue
                    if ext_title in t['title'] or t['title'] in ext_title:
                        best_note = t
                        break
                        
                if best_note:
                    cover = best_note.get("cover", "https://via.placeholder.com/140x180?text=No+Image")
                    cover = cover.replace("/format/heif/", "/format/webp/")
                    note_url = best_note.get("noteUrl", "") or best_note.get("note_url", "")
                    
                    # 【核心优化】如果没有 xsec_token 护照，直连会被拦截墙拦截。采用官方搜索跳板绕过。
                    if note_url and "xsec_token=" not in note_url and best_note.get("title"):
                        note_url = f"https://www.xiaohongshu.com/search_result/?keyword={urllib.parse.quote(best_note['title'])}&source=web_search_result"
                    
                    if line.startswith('**《' + ext_title + '》**') or line.startswith('- **《' + ext_title + '》**') or line.startswith('**' + ext_title + '**'):
                        if best_note['title'] not in processed_titles:
                            # Insert left-side cover highlight
                            cover_html = f'<a href="{note_url}" target="_blank" title="点击查看原笔记"><img src="{cover}" class="side-cover clickable-cover"></a>' if note_url else f'<img src="{cover}" class="side-cover">'
                            inject_html = f'<div class="note-highlight">{cover_html}<div class="note-content">'
                            processed_titles.add(best_note['title'])
                    
                    esc_full = re.escape(full_book_mark)
                    if note_url:
                        repl_str = f'<a class="tooltip-container" href="{note_url}" target="_blank" title="点击查看原笔记">{full_book_mark}<img src="{cover}" class="tooltip-img"></a>'
                    else:
                        repl_str = f'<span class="tooltip-container">{full_book_mark}<img src="{cover}" class="tooltip-img"></span>'
                    
                    styled_line = re.sub(r'\[' + esc_full + r'\]\([^)]+\)', repl_str, styled_line)
                    styled_line = re.sub(r'(?<!>)' + esc_full + r'(?!<)', repl_str, styled_line)

            styled_line = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', styled_line)
            styled_line = re.sub(r'\*(.*?)\*', r'<em>\1</em>', styled_line)
            styled_line = re.sub(r'`(.*?)`', r'<code>\1</code>', styled_line)
            # 全局兜底渲染剩余的 Markdown 链接
            styled_line = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" style="color:#ff2442; text-decoration:none;">\1</a>', styled_line)
            
            if inject_html:
                clean_text = styled_line.replace('- ', '', 1)
                html_output += inject_html + f'<div class="hl-text">{clean_text}</div>\n'
            elif line.startswith('- 点赞') and len(processed_titles) > 0:
                if '行动清单' not in current_h2:
                    html_output += f'<div class="metrics">{styled_line}</div></div></div>\n'
                else:
                    html_output += f'<li>{styled_line[2:]}</li>\n'
            elif re.sub(r'^[-\s\*]+', '', line).startswith('现象：') or re.sub(r'^[-\s\*]+', '', line).startswith('原理：') or re.sub(r'^[-\s\*]+', '', line).startswith('可抄走的做法：'):
                html_output += f'<div class="breakdown-item">{styled_line}</div>\n'
            elif line.startswith('- '):
                if 'SOP' in current_h2:
                    html_output += f'<div class="check-item"><span class="check-icon">✓</span><span class="check-text">{styled_line[2:]}</span></div>\n'
                else:
                    html_output += f'<li>{styled_line[2:]}</li>\n'
            elif styled_line.strip() == '':
                html_output += '\n'
            elif line.startswith('> '):
                html_output += f'<blockquote class="report-quote">{styled_line[2:]}</blockquote>\n'
            else:
                if '行动清单' in current_h2 and ':' in styled_line and not styled_line.startswith('<'):
                    parts = styled_line.split(":", 1)
                    html_output += f'<div class="check-item"><span class="check-icon">✓</span><span class="check-text"><strong>{parts[0]}:</strong> {parts[1]}</span></div>\n'
                elif '行动清单' in current_h2 and '：' in styled_line and not styled_line.startswith('<'):
                    parts = styled_line.split("：", 1)
                    html_output += f'<div class="check-item"><span class="check-icon">✓</span><span class="check-text"><strong>{parts[0]}：</strong> {parts[1]}</span></div>\n'
                else:
                    html_output += f'<p>{styled_line}</p>\n'
            pass
    if in_table:
        html_output += '</table>\n'

    full_html = f'''
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>小红书账号深度拆解报告</title>
        <meta name="referrer" content="no-referrer">
        <style>
            :root {{ --primary: #ff2442; --bg: #f5f6f8; --card: #ffffff; --text: #333; }}
            body {{ font-family: "PingFang SC", -apple-system, blinkmacsystemfont, roboto, sans-serif; background: var(--bg); color: var(--text); padding: 50px 20px; margin: 0; line-height: 1.7; }}
            .main-container {{ max-width: 1000px; margin: 0 auto; background: #fff; padding: 50px 60px; border-radius: 20px; box-shadow: 0 10px 40px rgba(0,0,0,0.05); }}
            
            h1 {{ border-bottom: 3px solid var(--primary); padding-bottom: 20px; margin-top:0; font-size: 2.2em; }}
            h2.section-title, h3.section-title {{ margin-top: 50px; color: var(--text); display: flex; align-items: center; font-size: 1.6em; border-left: 5px solid var(--primary); padding-left: 15px; background: linear-gradient(90deg, rgba(255,36,66,0.06) 0%, rgba(255,255,255,0) 100%); line-height: 1.4; }}
            p {{ color: #444; font-size: 1.05em; margin-bottom: 15px; }}
            blockquote.report-quote {{ border-left: 4px solid var(--primary); padding-left: 15px; margin: 15px 0; color: #666; background: #fffcfd; padding: 10px 15px; border-radius: 4px; font-size: 0.95em; }}
            
            /* Dashboard */
            .dashboard {{ display: flex; gap: 20px; margin: 30px 0; flex-wrap: wrap; }}
            .stat-card {{ min-width: 150px; flex: 1; background: #fdfdfd; border: 1px solid #eee; padding: 25px; border-radius: 12px; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.02); transition: transform 0.2s; }}
            .stat-card:hover {{ transform: translateY(-3px); }}
            .stat-card.highlight {{ border-color: rgba(255,36,66,0.3); background: rgba(255,36,66,0.02); }}
            .stat-value {{ font-size: 2em; font-weight: 800; color: #111; margin-bottom: 5px; }}
            .stat-card.highlight .stat-value {{ color: var(--primary); }}
            .stat-label {{ color: #888; font-size: 0.9em; }}
            
            /* Scroll Gallery */
            .gallery-scroll {{ display: flex; gap: 15px; overflow-x: auto; padding: 20px 0 30px 0; margin: 0 -15px; scrollbar-width: thin; }}
            .gallery-scroll::-webkit-scrollbar {{ height: 8px; }}
            .gallery-scroll::-webkit-scrollbar-thumb {{ background-color: #ddd; border-radius: 4px; }}
            .gallery-card {{ flex: 0 0 200px; background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 5px 15px rgba(0,0,0,0.08); position: relative; transition: transform 0.2s; }}
            .gallery-card:hover {{ transform: scale(1.03); }}
            /* 可点击跳转的卡片样式 */
            .gallery-card-link {{ flex: 0 0 200px; background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 5px 15px rgba(0,0,0,0.08); position: relative; transition: transform 0.2s, box-shadow 0.2s; text-decoration: none; color: inherit; display: block; cursor: pointer; }}
            .gallery-card-link:hover {{ transform: scale(1.05); box-shadow: 0 10px 30px rgba(255,36,66,0.18); }}
            .gallery-card-link:hover .link-hint {{ opacity: 1; }}
            .rank-badge {{ position: absolute; top: 10px; left: 10px; background: rgba(0,0,0,0.7); color: #fff; padding: 3px 10px; font-size: 0.8em; font-weight: bold; border-radius: 15px; z-index: 2; backdrop-filter: blur(4px); }}
            .gallery-card img, .gallery-card-link img {{ width: 100%; height: 260px; object-fit: cover; }}
            .gallery-info {{ padding: 12px; }}
            .g-title {{ font-size: 0.9em; font-weight: 600; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 8px; height: 2.8em; }}
            .g-likes {{ font-size: 0.85em; color: var(--primary); font-weight: bold; }}
            .link-hint {{ font-size: 0.78em; color: var(--primary); opacity: 0; transition: opacity 0.2s; margin-top: 6px; font-weight: 500; }}

            /* Panels */
            .visual-panel {{ display: flex; gap: 30px; margin: 30px 0; background: #fffcfd; padding: 30px; border-radius: 15px; border: 1px solid #ffedf0; }}
            .panel-section {{ flex: 1; }}
            .panel-title {{ font-weight: bold; color: var(--primary); margin-bottom: 20px; font-size: 1.1em; }}
            
            /* Wordcloud */
            .wordcloud-sm {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px; }}
            .dim-label {{ font-size: 0.85em; font-weight: bold; color: #666; margin-bottom: 6px; }}
            .wordcloud {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; align-content: flex-start; height: 100%; }}
            .bubble {{ padding: 10px 20px; border-radius: 50px; font-weight: bold; display: inline-flex; align-items: center; justify-content: center; box-shadow: 0 4px 10px rgba(0,0,0,0.05); animation: float 3s ease-in-out infinite alternate; }}
            @keyframes float {{ 0% {{ transform: translateY(0); }} 100% {{ transform: translateY(-5px); }} }}
            
            /* Pure CSS Chart */
            .css-chart-container {{ display: flex; align-items: center; gap: 30px; flex-wrap: wrap; }}
            .css-donut {{ width: 160px; height: 160px; border-radius: 50%; position: relative; box-shadow: 0 5px 15px rgba(0,0,0,0.08); }}
            .css-donut::before {{ content: ""; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 90px; height: 90px; background: #fffcfd; border-radius: 50%; }}
            .chart-legend {{ display: flex; flex-direction: column; gap: 8px; }}
            .legend-item {{ display: flex; align-items: center; font-size: 0.9em; color: #555; }}
            .color-box {{ width: 12px; height: 12px; border-radius: 3px; margin-right: 8px; display: inline-block; }}

            /* Action Checklist */
            .check-item {{ background: #fdfdfd; border-radius: 8px; padding: 15px 20px; display: flex; align-items: flex-start; margin-bottom: 12px; border: 1px solid #eee; transition: all 0.2s; }}
            .check-item:hover {{ border-color: rgba(255,36,66,0.3); background: #fffcfd; box-shadow: 0 4px 12px rgba(255,36,66,0.05); }}
            .check-icon {{ color: #4caf50; font-weight: bold; font-size: 1.2em; margin-right: 15px; margin-top: -2px; }}
            .check-text {{ flex: 1; }}

            /* Highlight Notes */
            .note-highlight {{ display: flex; align-items: flex-start; background: #fff; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.06); margin: 25px 0; border-left: 5px solid #ff2442; transition: transform 0.2s; flex-wrap: wrap; }}
            .note-highlight:hover {{ transform: translateY(-3px); box-shadow: 0 8px 25px rgba(0,0,0,0.08); }}
            .side-cover {{ width: 140px; height: 180px; object-fit: cover; border-radius: 8px; margin-right: 25px; margin-bottom: 15px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
            /* 可点击封面 */
            .clickable-cover {{ transition: transform 0.2s, box-shadow 0.2s; }}
            .clickable-cover:hover {{ transform: scale(1.04); box-shadow: 0 8px 20px rgba(255,36,66,0.2); cursor: pointer; }}
            .note-content {{ flex: 1; min-width: 250px; }}
            .hl-text {{ font-size: 1.1em; color:#222; margin-bottom:10px; }}
            .metrics {{ color: #666; font-size: 0.9em; margin-top: 15px; background: #f5f5f5; display: inline-block; padding: 6px 15px; border-radius: 20px; font-weight:500; border: 1px solid #eee; }}
            
            .breakdown-item {{ margin-bottom: 8px; padding-left: 15px; position: relative; }}
            .breakdown-item::before {{ content: "•"; position: absolute; left: 0; color: var(--primary); font-weight: bold; }}
            
            /* Tooltip（hover 预览 + 点击跳转，a 标签版本兼容样式）*/
            .tooltip-container {{ position: relative; color: var(--primary); font-weight: 600; cursor: pointer; border-bottom: 1px dashed var(--primary); text-decoration: none; }}
            .tooltip-container .tooltip-img {{ visibility: hidden; width: 180px; position: absolute; z-index: 100; bottom: 130%; left: 50%; transform: translateX(-50%); box-shadow: 0 10px 25px rgba(0,0,0,0.2); border-radius: 8px; opacity: 0; transition: all 0.3s; border: 3px solid #fff; }}
            .tooltip-container:hover .tooltip-img {{ visibility: visible; opacity: 1; bottom: 150%; }}
            .tooltip-container:hover {{ color: #c0001a; }}
            
            code {{ background: rgba(255,36,66,0.06); padding: 3px 8px; border-radius: 4px; font-size: 0.9em; color: var(--primary); word-break: break-all; }}
            strong {{ color: #111; }}
            blockquote {{ font-style: italic; border-left: 4px solid #ddd; margin: 20px 0; padding-left: 15px; color: #555; }}
            
            @media (max-width: 768px) {{
                .main-container {{ padding: 20px; }}
                .note-highlight {{ flex-direction: column; }}
                .side-cover {{ width: 100%; height: auto; aspect-ratio: 3/4; }}
            }}
        </style>
    </head>
    <body>
    <div class="main-container">
    {html_output}
    </div>
    </body>
    </html>
    '''

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_html)
    print(f'✅ 可视化报告已生成: {output_path}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="生成小红书账号拆解 HTML 报告")
    parser.add_argument("--md", required=True, help="AI 生成的 11 段 Markdown 报告文件")
    parser.add_argument("--json", required=True, help="analyzer 输出的最终 JSON 数据文件")
    parser.add_argument("--out", required=True, help="输出 HTML 文件路径")
    
    args = parser.parse_args()
    generate_visual_html(args.md, args.json, args.out)
