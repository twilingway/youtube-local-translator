"""Generate a local, dependency-free audio A/B page; no autoplay or network."""
import html,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
folder=ROOT/'reports/listening';folder.mkdir(exist_ok=True)
def player(label,file):
    return f'<article><h3>{html.escape(label)}</h3><audio controls preload="metadata" src="{html.escape(file)}" aria-label="{html.escape(label)}"></audio></article>'
parts=['''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Сравнение русских голосов</title>
<style>:root{color-scheme:dark;font:16px system-ui;background:#101318;color:#eee}body{max-width:1080px;margin:32px auto;padding:0 20px}h1{font-size:30px}h2{margin:28px 0 12px}h3{font-size:16px;margin:0 0 16px}p{line-height:1.5;color:#bfc8d5}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}article{background:#1a222d;border:1px solid #344456;border-radius:12px;padding:18px}audio{width:100%;height:42px}blockquote{margin:16px 0;padding:12px 16px;background:#17202b;border-left:3px solid #5ca9ff;line-height:1.5}.note{padding:12px 16px;border:1px solid #546578;border-radius:8px}select{font:inherit;color:inherit;background:#202a38;padding:6px;border-radius:6px}</style>
<body><h1>Сравнение русских голосов</h1><p>Послушайте одну и ту же фразу в разных моделях. При запуске следующего примера предыдущий останавливается. Файлы уже созданы: ожидать синтез не нужно.</p>
<label>Скорость прослушивания <select id="rate"><option value="0.85">0.85×</option><option value="1" selected>1×</option><option value="1.15">1.15×</option></select></label>''']
source=folder/'source.json'
if source.exists():
    data=json.loads(source.read_text(encoding='utf-8'))
    parts.append(f'<h2>Голоса из выбранного ролика</h2><p>{html.escape(data.get("title", "YouTube"))}</p>')
    for item in data['stored_samples']:
        parts.append(f'<h2>Образец {item["id"]} · {item["video_start"]:.1f}–{item["video_end"]:.1f} с</h2><p>Слева — звук из вашей вкладки. Модели произносят одну контрольную фразу для сравнения тембра. Номер образца — автоматическая метка, а не подтверждённая личность.</p><blockquote>{html.escape(item.get("phrase",item["translation"]))}</blockquote><div class="grid">')
        parts.append(player('Оригинальный голос',item.get('original_listening',item['file'])))
        qwen=f'actor-{item["id"]}-qwen.wav'
        if (folder/qwen).exists():parts.append(player('Qwen Base по этому оригинальному образцу',qwen))
        if item.get('silero_voices'):
            voice=item['silero_selected'];options=''.join(f'<option value="{v["file"]}" {"selected" if k==voice else ""}>{k}</option>' for k,v in item['silero_voices'].items())
            parts.append(f'<article><h3>Silero · выбор тембра</h3><select class="voice">{options}</select><p>Стартовый вариант выбран по высоте голоса; можно сравнить все пять.</p><audio controls preload="metadata" src="{item["silero_voices"][voice]["file"]}" aria-label="Silero образец {item["id"]}"></audio></article>')
        elif (folder/f'actor-{item["id"]}-silero.wav').exists():parts.append(player('Silero',f'actor-{item["id"]}-silero.wav'))
        parts.append('</div>')
else:parts.append('<p class="note">Пока это тест готовых голосов. Qwen Base использовал синтетические образцы Silero; это ещё не голоса персонажей из YouTube.</p>')
texts=json.loads((ROOT/'reports/tts-comparison/silero.json').read_text(encoding='utf-8'))['texts']
for i,text in enumerate(texts):
    parts.append(f'<h2>{"Короткая" if i==0 else "Длинная"} фраза</h2><blockquote>{html.escape(text)}</blockquote>')
    for voice,label in [('male','Мужской профиль'),('female','Женский профиль')]:
        parts.append(f'<h3>{label}</h3><div class="grid">')
        for engine,name in [('silero','Silero v5.6'),('qwen-python','Qwen CustomVoice 0.6B'),('qwen-native','Qwen Base 1.7B · образец Silero')]:
            file=f'../tts-comparison/{engine}-{i}-{voice}.wav'
            if (folder/file).exists():parts.append(player(name,file))
        parts.append('</div>')
parts.append('''<p>Это сравнение конкретных локальных запусков. Готовые голоса и клонирование по образцу решают разные задачи. Сходство тембра и качество произношения оцените прослушиванием.</p>
<script>const all=[...document.querySelectorAll('audio')];for(const audio of all)audio.addEventListener('play',()=>{for(const other of all)if(other!==audio)other.pause();});document.querySelector('#rate').onchange=e=>{for(const audio of all){audio.preservesPitch=true;audio.defaultPlaybackRate=Number(e.target.value);audio.playbackRate=audio.defaultPlaybackRate;}};for(const select of document.querySelectorAll('.voice'))select.onchange=()=>{const audio=select.closest('article').querySelector('audio');audio.pause();audio.src=select.value;audio.defaultPlaybackRate=Number(document.querySelector('#rate').value);audio.playbackRate=audio.defaultPlaybackRate;audio.preservesPitch=true;};</script></body></html>''')
(folder/'index.html').write_text('\n'.join(parts),encoding='utf-8')
print(folder/'index.html')
