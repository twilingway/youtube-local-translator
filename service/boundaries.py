"""Compare ASR overlap by whole words and time, before translation or TTS."""
import re

def word_key(text):
    return re.sub(r'\W+','',text.casefold())

def matched_prefix(previous,current,boundary):
    """Drop an already committed suffix only when text AND audio time match."""
    if not previous or not current:return 0
    best=(0,0)
    for begin in range(min(12,len(current))):
        for count in range(1,min(24,len(previous),len(current)-begin)+1):
            old=previous[-count:];new=current[begin:begin+count]
            if new[-1]['start']>=boundary or abs(new[-1]['end']-old[-1]['end'])>.6:continue
            keys=[word_key(w['text']) for w in old]
            if not all(keys) or keys!=[word_key(w['text']) for w in new]:continue
            if count==1 and (len(keys[0])<3 or abs(new[0]['start']-old[0]['start'])>.2):continue
            if count>best[0]:best=(count,begin+count)
    return best[1]
