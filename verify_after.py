# -*- coding: utf-8 -*-
# @version 1.17.0
"""改后回归验证：导入无冲突 + 命中量 + 输出差异审计（只允许命中行变化）。"""
import sys, hashlib, re
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
import subtitle_calib_merged as M

R2 = r"D:\原片\Reacting to ALL the resonator showcases - Wuthering Waves\【字幕】Reacting to ALL the resonator showcases - Wuthering Waves.en-谷歌翻译.calib.r2.srt"

print('import OK | ENTITIES:', len(M.ENTITIES), '| BILINGUAL_TERMS:', len(M.BILINGUAL_TERMS),
      '| CONTEXT_MAP:', len(M.CONTEXT_MAP))

# 新增裸键必须已进表
for k in ['团津', '千纱', '灵阳', '尚丽瑶', '罗蒂亚', '肖尔基珀', '加尔雷娜', '沙科纳', '卡蒂拉', '西格丽卡']:
    print(f'  {k} -> {M.BILINGUAL_TERMS.get(k)}')

rows, hits = M.process(R2, 'opt_out.srt', mode='bi')
print('process rows:', len(rows))
for num, old, new, ref in rows:
    print(f'#{num}\n  OLD: {old}\n  NEW: {new}\n  REF: {ref[:70]}')

# 与基线对比：术语表命中导致的改动，不得破坏结构
print('\nmd5 opt_out:', hashlib.md5(open('opt_out.srt', 'rb').read()).hexdigest())
