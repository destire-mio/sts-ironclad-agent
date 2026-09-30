live4 进行中。原始目标：teacher 固定3900012000–3900012099 100尝试；student固定3900016000–3900016031 32尝试。保持不重跑，不重新搜索同一决策，不云端计算，不Git发布。当前入口 run.sh -> live4/cli.py；teacher数据仍在live3/teacher。

本轮完成：下载 distill2 frozen模型90b93734...094fa2b，freeze/schema位于live4/models；云端12份代码与本机一致。新student适配六组输入/11195维，与生产Writer CSR + Dataset.batch逐位核对，401状态1991候选离线通过；实际每决策继续核对。老师/全部P300规则函数/父模型层choose设tripwire，6负向探针通过。默认学生继承旧16局v1，补后16局v2，不能称v2有32局。曾异步询问另授权32个新种子，未收到答复，采用固定原范围、按模型分组口径。

teacher新增2012/2013/2014为3win，累计15局8win7loss0fault，1对胜负分歧。student新6016/6017已win；其余看progress.json，不重试已建目录。

定位并修复2007/step794 TimeWarp+UnceasingTop顺序：原版callEndTurnEarlySequence -> releaseCard -> refreshHandLayout，空手排入DrawCards1，再forced endTurn。旧核心漏draw。live4/top-candidate/BattleContext.cpp为唯一core改变，51保存动作对比：target30差异->0，其他50结果不变（9本来带差异），0search/0Java重启。live3完全保留，派生live4/runtime，3个模块用同一修改core重链接，nested manifest/identity/live-manifest已更新并通过加载及401特征检查。runtime-history.json给旧/新hash，teacher2015起、student6016起使用派生包。未重跑旧2007或任何整局。

当前学生dispatcher工具session7230，日志live4/evidence/student-batch.log；完成后立刻 `./run.sh --policy teacher --workers 4 --hours 24 >> live4/evidence/teacher-batch.log 2>&1` 补余85。teacher目前drain标志正常，新启动清掉它。

磁盘启动前2.94GB，不足3；本目录旧gz日志逐内容hash压缩释放0.59GB，删除28个哈希核验重复jar是APFS clone故未显著释放物理空间。214个live1/live2结束实例打instance.tar.xz并逐文件hash核验后移除散文件，释放约0.32GB。ledger在evidence。动态disk调度3GB+350MB每在途实例，当前通常1–2Java，max4且Xmx384m；global其他Java计数也算。uv cache prune异步问过但未获答复，没有执行。

另有本任务后台监控session39288每5秒写resource-samples.jsonl，touch live4/monitor-stop结束；归档watch session45084针对live3/student、live3/teacher、live4/student的packed结果，将original/instance无损tar.xz并核对内容SHA，metadata在original/instance-archive.json；touch live4/archive-stop结束。只处理cleanup.remaining=[]和ps无该实例Java的目录。最终等待完成后停两个watch，不遗留进程。实例日志在压缩包中，步骤/RPC/终局仍原位置。

审计入口 python live4/audit.py；31旧结束局初审errors=[]/source_changes=[]。最终须132尝试、无pending/running/Java、完整audit后 `python live4/write_report.py`。目前write_report脚本已写尚待终审；目标scratchpad/parity/live4-report.md。README已改live4入口及混合版本限制，末尾report链接待最终文件生成。派生runtime为局部规则修复，报告不能称100个相同冻结版本；0fault不等于全状态parity。

live4/delivery-manifest.json冻结当前cli/runner/student/代码/engine。改动须保留旧manifest并说明版本分组，尤其cohort学生绑定student_code_sha256。当前没有已知运行故障，不要为猜测改更多代码。父live3清单未修改。旧老师开始singleworker时发现cli在active变空就退出的问题，live4已改继续pending；2012自然终局后恢复2013，不是重试。
