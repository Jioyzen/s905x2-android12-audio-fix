# S905X2 Android 12 音频修复：最终产物与原始镜像对照

本项目整理杂牌 Amlogic S905X2／G12A 盒子在移植 Android 12 固件上的最终音频系统修复。固件来源为 Skyworth／Strong LEAP-S1，实际盒子硬件不是 LEAP-S1。用户已确认本次音频使用要求全部满足；最终方案覆盖飞牛 TV 的 IJK 路径、默影视的 ExoPlayer 路径，以及关闭直通时的系统软件解码。

归档完成日期：**2026-10-29**。本次工作仅离线核对、归档和构建，盒子已拆除，没有进行新的实机测试。音频载荷以 2026-09-30 已固化版本为基础，合入 2026-10-01 已验证并固化的普通 DTS 满周期帧修复；不采用 9 月 28 日的早期缓冲实验版。

## 对照基线与交付范围

原始镜像：`sei500奈飞安卓12.img`，1832295392 字节。

```text
SHA256 2916c7cf174ca26de65bae2b20edd7fa9a59d5f73ddfad2b4eb4b7e0ae3320c1
```

本次从这个 IMG 的 super 项重新展开 Android sparse，验证 LP 几何、头部和表校验和，提取四个逻辑分区并核对哈希，再读取原始文件。最终 12 个载荷也分别从已刷写归档镜像提取，与发布文件逐字节／SHA256 对照。证据在 [原始镜像清单](manifests/original-image.json)、[原始文件核验](evidence/original-audit.json) 和 [最终镜像文件元数据](evidence/final-snapshot-file-metadata.json)。

**最终音频文件清单为 10 个替换文件、2 个新增文件、1 个新增空目录，涉及 vendor、system、product。** 下表列全路径、修改方式和用途。它是音频修复对照清单，不是整个 ROM 的全部移植差异；遥控、LED、设置菜单、ADB／启动、内核移植及后续 CoreELEC 开发不计入音频载荷。

## 修改／新增文件总表

| 动作 | Android 落盘文件路径 | 修改方法 | 修复问题／实现功能 |
|---|---|---|---|
| 替换 | `/vendor/lib/hw/audio.primary.amlogic.so` | 原厂 ARM32/Thumb HAL 上修改指令、扩展 ELF 并注入格式专用处理 | 恢复 HD 格式白名单；修复 HBR 载波、呈现时钟、TrueHD 缓冲／延迟、seek、切轨竞态和 HDMI N1 锁存；兼容 ExoPlayer 原生 DTS-HD 及已验证的满周期 DTS core |
| 替换 | `/vendor/lib/libdroidaudiospdif.so` | 保持 SPDIFEncoder ABI，以 AOSP 扫描器外壳＋FFmpeg parser／SPDIF muxer 重建 | 增加 DTS-HD／TrueHD MAT 打包；丢弃 seek 后孤立 EXSS，flush 重建状态；修复满周期 DTS 帧加 IEC 头后溢出清零 |
| 替换 | `/vendor/etc/audio_policy_configuration.xml` | 重写输出端口／路由，补齐两端 profiles 与声道掩码 | 声明 DTS-HD、TrueHD 和 DTS-ES 6.1；direct raw 允许两个句柄交接；HDMI 路由匹配实际压缩输出 |
| 替换 | `/vendor/lib/libstagefrighthw.so` | 用本项目 FFmpeg 软件 OMX 包装器替换原插件入口 | 提供 AC3／E-AC3／DTS／DTS-HD／DTS Express／TrueHD 系统软解、立体声下混、TrueHD 约 20 ms 批量 PCM 输出；视频等原组件继续委托原厂库 |
| 新增 | `/vendor/lib/libstagefrighthw_original.so` | 将原镜像 libstagefrighthw.so 原样复制到新名称 | 保存原厂视频及其他 OMX 组件的运行依赖；包装器通过 dlopen 委托，不是闲置备份 |
| 替换 | `/vendor/etc/media_codecs.xml` | 在原配置中注册软件 OMX 组件及参数范围 | 让系统 MediaCodecList 可选 AC3、E-AC3、标准 TrueHD 软件解码组件 |
| 替换 | `/vendor/etc/media_codecs_ext.xml` | 补充 DTS 家族软件 OMX 组件声明 | 让 DTS、DTS-HD、DTS Express 的标准系统解码路径匹配新实现 |
| 替换 | `/system/lib/libmediavendor_ext.so` | 原二进制局部 Thumb／字符串／参数分支补丁 | 兼容标准 audio/true-hd、旧 audio/truehd 和 TrueHD 厂商压缩参数查询，解决 ACodec 初始化失败 |
| 替换 | `/system/lib/libstagefright_xmlparser.so` | 在既有角色表未命中时增加 TrueHD MIME 回退 | 将标准 audio/true-hd 映射到对应 decoder／encoder 角色，保留原表行为 |
| 替换 | `/system/apex/com.android.vndk.current/lib/libstagefright_xmlparser.so` | 对 VNDK 独立版本单独打角色映射补丁 | 覆盖厂商进程实际使用的 VNDK 解析库；不能与 system 版互换 |
| 替换 | `/product/etc/build.prop` | 仅替换一项属性：ro.af.client_heap_size_kbyte=2048 → 8192 | AudioFlinger 每客户端共享内存上限由 2 MiB 提高到 8 MiB；解决 ExoPlayer DTS-HD AudioTrack 申请 4194536 字节时 ENOMEM／-12 |
| 新增 | `/vendor/etc/init/zz-nonms12-audio.rc` | 新增 Android init 的 post-fs-data／boot_completed 动作 | 开机 bind 空目录到 /odm/lib；授予音频 HAL 正式 N1 修复所需 HDMI 节点 DAC 权限 |
| 新增空目录 | `/vendor/etc/audio-noms12-empty/` | 创建 root:root／0755 的真正空目录 | 作为开机 `/odm/lib` 遮罩源，使本方案运行于已验收的非 MS12 路径 |
| 运行时挂载 | `/odm/lib` | init 在 post-fs-data bind 上述空目录 | ODM 原文件保留在分区中，运行时不可见；同时会遮住该目录的其他库，新软解不依赖这些隐藏库 |
| 运行时权限 | `/sys/class/amhdmitx/amhdmitx0/debug` | init 设置 root:audio／0220，boot_completed 后再设一次 | 允许 HAL 在 PCM 已运行后对当前 HDMI AUD_N1 原值写回一次，修复 AC3 切入后停旧格式／无声 |

全部普通载荷文件为 root:root／0644。vendor 库标签为 `vendor_file`，vendor 配置和新增空目录为 `vendor_configs_file`，system 三库为 `system_lib_file`，product build.prop 为 `system_file`。完整标签、大小、原始／最终 SHA256、镜像内 inode 路径及来源见 [payload.json](manifests/payload.json)。Git 不保存空目录，使用导出脚本重建；不能放一个 `.gitkeep` 后将非空目录当作正式遮罩目录。

VNDK 库的运行路径是 `/apex/com.android.vndk.v31/lib/libstagefright_xmlparser.so`；本 ROM 采用展开 APEX，离线实际落盘路径是表中的 `/system/apex/com.android.vndk.current/lib/...`。system 分区内部还带一层 `/system` 前缀，具体 inode 路径已逐文件记录。

## 已实现的修复

- **HD 直通能力链**：策略显式声明格式、采样率和声道掩码；HAL 允许 HD 格式；FFmpeg 生成 DTS-HD IEC61937／TrueHD MAT；以正确 HBR 速率输出原压缩位流，由功放解码。
- **画速、音画同步与 seek**：对 IJK DTS 别名路径修正 HBR 载波和返回的内容帧单位；TrueHD 使用专用缓冲与正确延迟换算；flush 清除旧状态，打包器跳过 seek 中孤立 EXSS 并重建 parser／muxer。
- **连续切轨**：旧输出关闭时检查槽指针归属；TrueHD 首次完整 MAT 输出后进行一次建流重置；AC3 在硬件运行后同值重锁存 N1，避免只点亮旧标识或持续无声。
- **ExoPlayer 原生 DTS-HD**：同时修复 AudioTrack 共享内存上限和原生 `DTS_HD` 分支遗漏的 192 kHz 设置，两项均需要。
- **普通 DTS／DTS-ES**：策略补 6.1 掩码；已识别 DTS-ES core 保持普通载波；对已验证 BE／48 kHz／512 样本／2048 字节满帧 core，修复错误 HBR 提升和 IEC 头导致的周期溢出。
- **系统软解与电视播放**：标准 MediaCodec 可使用本项目 FFmpeg OMX 解码，输出立体声 PCM16；TrueHD 按约 20 ms 聚合，降低小帧回调开销。视频等其他 OMX 组件保留原厂实现。

细节、关键指令地址、格式／时钟口径和失败方案见 [修复原理与修改方法](docs/修复原理与修改方法.md)。

## 原始／最终文件大小与完整哈希

| Android 路径 | 原始字节数 | 最终字节数 | 最终 SHA256 |
|---|---:|---:|---|
| `/vendor/lib/hw/audio.primary.amlogic.so` | 460260 | 464356 | `6b582b0c2ad3e5ce9613abd559fda73688a5167da20fa880d55881914fce3215` |
| `/vendor/lib/libdroidaudiospdif.so` | 12564 | 613392 | `1e1c8ee210eb13cea4a304944fc16992a3d82c44f9a41324316db78a49ae4130` |
| `/vendor/etc/audio_policy_configuration.xml` | 14299 | 17228 | `0418970d94e39dbe2595804226c73d7c6a260f210d7dbdc3ad2699c3d804225b` |
| `/vendor/lib/libstagefrighthw.so` | 30616 | 2953668 | `1a5ea7257a56dc072d72860bb22fcbedb264c3eb4e76002e31d49f2db5241600` |
| `/vendor/lib/libstagefrighthw_original.so` | 不存在 | 30616 | `f96ab54c54ca4c80afd61feb9848b1a2b9097db92060fc7cf087fa24b5db2a6a` |
| `/vendor/etc/media_codecs.xml` | 16338 | 17044 | `af0d237b26eb3e8918fb5313f7ba10eabc7805861920c7468236f3f302d021be` |
| `/vendor/etc/media_codecs_ext.xml` | 9158 | 9170 | `fb5cf35291660e7939c1324cac2356b278e42989eeac6cda38ecb2e04b2fde2e` |
| `/system/lib/libmediavendor_ext.so` | 28044 | 28044 | `7abdbf09f4b47082b410c957409c8c12f81fd036213f9ddfe241561bfcf5a6cd` |
| `/system/lib/libstagefright_xmlparser.so` | 73532 | 73532 | `ee1a2eae2896e505f51166f49816660353082720f10796bf693535d88f2914b2` |
| `/system/apex/com.android.vndk.current/lib/libstagefright_xmlparser.so` | 80080 | 80080 | `c14f9af1e39ae819873b559aa8a76766c0a3f28dc298b755ae51eb718f43825b` |
| `/product/etc/build.prop` | 2386 | 2386 | `5aa81cad94ed52b717155ef864d7d7e142442624d372d0df497c4bc6c1e5374e` |
| `/vendor/etc/init/zz-nonms12-audio.rc` | 不存在 | 573 | `9af6a0d93d911b78a26c3652f51aa10f93ca3983846ef9ed12b977da20fe27f4` |

每个原始文件的完整 SHA256 也保存在 [payload.json](manifests/payload.json)。原始文件位于 `baseline/rootfs/`，最终载荷位于 `artifacts/rootfs/`，目录与 Android 落盘结构一一对应。新增 `libstagefrighthw_original.so` 与原镜像的 `libstagefrighthw.so` 完全相同。

## 文件结构

```text
README.md                         本文：最终交付文档
artifacts/rootfs/                  12 个最终运行文件，按 Android 路径放置
baseline/rootfs/                   10 个被替换文件的原镜像版本
manifests/payload.json             路径、动作、哈希、来源、权限、SELinux、空目录
manifests/original-image.json      指定原始 IMG、super 项和逻辑分区哈希
manifests/binary-deltas.json       HAL 和 system 三库的完整逐字节变更
manifests/policy-semantic-diff.json 去除排版噪声后的策略结构变化
patches/                          XML 与 build.prop 的完整文本差异
src/hal/                          最终补丁涉及的 Thumb 汇编及历史构建参考
src/spdif/                        最终 SPDIF 外壳、适配代码、头文件、冻结静态库
src/decoder/                      软件 OMX 源码、头文件、冻结静态库和 MIME 补丁源
third_party/                      两个固定版本 FFmpeg 完整源码包及许可说明
scripts/                          离线核验、精确重建、重编译和载荷导出工具
evidence/                         原镜像／最终镜像元数据、验证与历史验收依据
docs/                             原理、方法、持久化与验收边界
```

## 校验与重建

主机需要 Python 3.12+；解包原镜像另需 `debugfs`（e2fsprogs）。这些命令只处理主机文件。

```bash
python3 scripts/verify_release.py
python3 scripts/reconstruct_binaries.py
python3 scripts/export_rootfs.py _build/exported-rootfs
```

第一条核验 12 个载荷和 10 个原始文件、全部包文件校验和、XML 解析、build.prop 单属性变化和原厂 OMX 委托依赖，并测试损坏输入会被拒绝。第二条从本项目保存的原始文件精确重建 HAL 及三个系统补丁库；输出必须与最终产物字节一致。第三条导出 12 个文件并创建必需空目录；它不自动设置 Android 镜像的所有权和 SELinux xattr，写镜像时按 manifest 恢复。

使用自己的指定原 IMG 重做基线审计：

```bash
python3 scripts/audit_original.py /path/to/sei500奈飞安卓12.img --out _audit/new-reference
```

工具先校验整个 IMG 和 super 项，再解包并验证 LP 校验和／逻辑分区 SHA256；输入不符会停止。输出目录必须不存在，过程中需要约 4 GiB 临时空间，不访问盒子。

使用 Linux x86_64 Android NDK 28.2.13676358、仓库中的源码及冻结 FFmpeg 静态库重新编译两个新实现库：

```bash
export ANDROID_NDK_HOME=/path/to/android-ndk-28.2.13676358
python3 scripts/build_audio_libraries.py
```

本次归档已执行该命令：SPDIF 打包库为 `1e1c8ee2…`，OMX 包装库为 `1a5ea725…`，**两者均与最终发布文件逐字节一致**。FFmpeg 完整源码和配置一并保留；本命令重编译本项目代码并链接归档的 FFmpeg 静态库，不宣称已从零重编译所有上游依赖。自改 FFmpeg 后可用 `--spdif-ffmpeg-libs`／`--decoder-ffmpeg-libs` 指定替代静态库。`--relink-frozen` 可使用归档适配对象文件重链接。构建输出均在 `_build/native/`，不覆盖正式载荷。

## 持久化、验收与边界

最终音频已在历史实机阶段写入 vendor／system／product 并完成整分区直接回读校验。2026-10-01 最后两项音频增量所在 vendor 镜像为 `c18cf321…`；完整记录见 [持久化与验证](docs/持久化与验证.md)。本仓库交付文件级音频载荷，不上传包含遥控、设置或其他移植改动的整机镜像，也不将历史固定 extent 偏移包装成通用刷机命令。

用户已确认实际有声、功放识别、正常画速、同步、长 seek 与切轨满足要求；2026-10-01 满帧 DTS 修复有单独实播反馈和写后回读证据。原始阶段记录中的“尚未持久化”“待回归”按其时间解释，不替代后续刷写结果。本次盒子离线，不能对当前 eMMC 状态或未测试样本作新实测结论。

最终音频方案不修改播放器 APK。飞牛 TV 1.4.1 曾对 `dts / 8ch / 自动` 执行内部 max6 判断而回退 PCM；其“强制直通”绕过应用门控。TCL 对照也最终确认须强制直通。这是独立的应用能力判断边界，不能把盒子后级修好写成已经修复飞牛“自动”逻辑。本项目不交付 APP 补丁、厂商／SDK 伪装、常驻探针、轮询监测器或定时 FIFO 复位程序。

系统软解面向立体声电视兼容播放，不提供多声道 PCM／Atmos 或 DTS:X 对象渲染；需要原格式由功放处理时使用直通。满帧 DTS HAL 识别有明确样本和分块限制，强制 tunnel、罕见 DTS 变体和其他硬件组合不作全覆盖声明。现有 ROM 的 SELinux permissive 是历史前提，本项目未新增 SELinux 策略；不能假设直接移入任意 enforcing ROM 即可工作。

来源与第三方许可见 [第三方说明](third_party/README.md)。未将厂商固件二进制重新声明为本项目自有开源代码。
