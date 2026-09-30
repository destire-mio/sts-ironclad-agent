# 盾矛预算改变后的四个胜负分歧

列出全部3个救回与1个损失，不按故事好坏挑选。两分支从同一盾矛入口开始；后续HP、药水、遗物计数、RNG等可以随合法动作改变。

- 3900012719：Heart入口RNG相同=False；记录字段指纹相同=False；首手相同=True。
- 3900012494：Heart入口RNG相同=False；记录字段指纹相同=False；首手相同=True。
- 3900012154：Heart入口RNG相同=True；记录字段指纹相同=False；首手相同=True。
- 3900012688：Heart入口RNG相同=False；记录字段指纹相同=False；首手相同=True。

| seed | 策略 | Heart战前HP | 最大HP | 药水 | Heart胜 |
|---|---|---|---|---|---|
| 3900012719 | base | 126 | 126 | FLEX_POTION, EMPTY_POTION_SLOT, EMPTY_POTION_SLOT, EMPTY_POTION_SLOT | False |
| 3900012719 | candidate | 126 | 126 | FLEX_POTION, EMPTY_POTION_SLOT, EMPTY_POTION_SLOT, EMPTY_POTION_SLOT | True |
| 3900012494 | base | 75 | 85 | EMPTY_POTION_SLOT, EMPTY_POTION_SLOT, EMPTY_POTION_SLOT, EMPTY_POTION_SLOT | False |
| 3900012494 | candidate | 85 | 85 | BLOOD_POTION, EMPTY_POTION_SLOT, EMPTY_POTION_SLOT, EMPTY_POTION_SLOT | True |
| 3900012154 | base | 79 | 92 | SWIFT_POTION, EMPTY_POTION_SLOT | False |
| 3900012154 | candidate | 84 | 92 | SWIFT_POTION, EMPTY_POTION_SLOT | True |
| 3900012688 | base | 28 | 76 | EMPTY_POTION_SLOT, EMPTY_POTION_SLOT | True |
| 3900012688 | candidate | 50 | 76 | EMPTY_POTION_SLOT, EMPTY_POTION_SLOT | False |

2688从28HP提高到50HP却由胜转负；不能把入场HP作为胜负的充分条件。2719两线都是126HP、相同药水数量，终局仍不同；完整入口字段与首手见 spear-case-entries.json。收益来自整条合法分叉的终局，不能全部归因于多保住几滴血。
