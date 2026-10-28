# 第三方来源与构建材料

本仓库包含用于归档核验的厂商原始／修改二进制、AOSP兼容代码、本项目适配代码、FFmpeg源码与冻结构建依赖。各部分保留其来源和适用许可；没有将全部文件统一重新许可为本项目自有代码。

| 材料 | 来源／版本 | 用途 |
|---|---|---|
| baseline/rootfs 的原始二进制与配置 | 用户指定的 sei500奈飞安卓12.img | 原始参照和精确二进制重建输入 |
| artifacts/rootfs 的HAL／系统库补丁 | 上述固件原件与本项目逐字节修改 | 最终运行载荷 |
| AOSP SPDIF扫描器、接口头文件、OMX接口头文件 | 历史工作区保存的AOSP兼容实现，文件内保留原有声明 | 构建SPDIF兼容外壳与OMX包装器 |
| FFmpeg-n8.1.3-source.tar.xz | FFmpeg commit 1041abdc962f4cc4f394aa8de9dc5236c0c3b9e7 | SPDIF muxer／DCA、MLP parser的完整源码 |
| FFmpeg-n6.1.1-source.tar.xz | FFmpeg commit e38092ef9395d7049f871ef4d5411eb410e283e0 | AC3／EAC3／DCA／TrueHD／MLP解码及swresample完整源码 |
| src/*/frozen-ffmpeg | 上述版本的冻结静态库和生成头文件 | 重链接与精确复编；config.h保留实际选项 |
| src/*/libstub | 本ROM的平台依赖库 | 主机交叉链接所需，不是Android新增部署文件 |
| src/decoder/SurroundDecoder.o、src/spdif/ffmpeg_hdpack.o | 本项目最终适配代码对象 | 支持重链接替换静态FFmpeg依赖 |

两个冻结FFmpeg配置的CONFIG_GPL、CONFIG_NONFREE、CONFIG_VERSION3均为0。完整源码包由对应干净git提交的git archive生成，哈希记录于manifests/upstreams.json，FFmpeg许可文件位于licenses/ffmpeg/。AOSP相关Apache2.0文本位于licenses/Apache-2.0.txt；具体文件版权声明保留在各源文件中。

FFmpeg上游：https://ffmpeg.org/ ，源码仓库：https://git.ffmpeg.org/ffmpeg.git 。Android相关上游：https://android.googlesource.com/ 。

主机重编译入口为scripts/build_audio_libraries.py。它不访问网络，使用仓库源码与冻结静态库；也支持通过命令行替换静态库后重链接。完整从零构建FFmpeg时，应使用对应源码版本及frozen-ffmpeg/config.h保存的编译选项；新的工具链／配置可能改变文件哈希，需要作为新版本重新核验。许可文件的附带不构成对厂商固件版权的重新授权。

src/hal/history及src/decoder/patch_*保留历史补丁方法，其中部分脚本使用原工作区路径和中间输入；当前支持的原厂到最终HAL／系统库精确重建工具是scripts/reconstruct_binaries.py。新的目录布局只调整了src/spdif/ffmpeg_hdpack.c中的两处include路径，完整来源哈希及归档调整记录于source-provenance.json。
