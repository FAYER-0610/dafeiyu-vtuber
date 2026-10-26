"""生成大肥鱼的 OBS 场景集合、配置文件和启动脚本（OBS 要先关掉）。

游戏画面延迟：OBS 自带的“渲染延迟”最多 0.5 秒，所以绕一圈——
“游戏原画”场景只放游戏采集，虚拟摄像机输出这个场景；正式场景再把虚拟摄像机当视频采集设备接回来，
挂“视频延迟（异步）”滤镜。游戏声音单独用应用音频采集，同步偏移同样的秒数。她的声音和字幕不延迟。
秒数取 config.yaml 的 overlay.game_delay_seconds，改了重新跑一次本脚本。

    python scripts/make_obs.py [--obs-dir %APPDATA%\\obs-studio] [--obs-exe ...\\obs64.exe]

不改已有的场景集合和配置文件；同名的旧文件先备份成 .bak-时间。
"""
import argparse
import configparser
from datetime import datetime
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import sys
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[1]
NAME = 'DaFeiYu'  # 配置文件和场景集合名；用英文是因为中文命令行参数传给 OBS 会乱码
STAGE = '大肥鱼直播'
RAW = '游戏原画'
CANVAS = '6c69626f-6273-4c00-9d88-c5136d61696e'  # OBS 主画布固定的 uuid
GAME_WINDOW = 'Slay the Spire 2:Engine:SlayTheSpire2.exe'  # priority 2：按 exe 匹配，标题/类名对不上也能找到
OBS_EXES = [r'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
            r'C:\Program Files (x86)\Steam\steamapps\common\OBS Studio\bin\64bit\obs64.exe']


def source(kind, name, settings, **extra):
    return {'name': name, 'uuid': str(uuid.uuid4()), 'id': kind, 'versioned_id': kind, 'settings': settings,
            'mixers': 255, 'sync': 0, 'flags': 0, 'volume': 1.0, 'balance': 0.5, 'enabled': True, 'muted': False,
            'hotkeys': {}, 'monitoring_type': 0, 'private_settings': {}, **extra}


def item(src, n, x=0, y=0, box=None):
    # box=(宽, 高)：等比缩放塞进这个框（OBS 的“缩放到内部”）；不给就原尺寸。
    return {'name': src['name'], 'source_uuid': src['uuid'], 'visible': True, 'locked': False, 'rot': 0.0,
            'align': 5, 'bounds_type': 2 if box else 0, 'bounds_align': 0, 'bounds_crop': False,
            'crop_left': 0, 'crop_top': 0, 'crop_right': 0, 'crop_bottom': 0, 'id': n, 'group_item_backup': False,
            'pos': {'x': float(x), 'y': float(y)}, 'scale': {'x': 1.0, 'y': 1.0},
            'bounds': {'x': float(box[0]), 'y': float(box[1])} if box else {'x': 0.0, 'y': 0.0},
            'scale_filter': 'disable', 'blend_method': 'default', 'blend_type': 'normal',
            'show_transition': {'duration': 0}, 'hide_transition': {'duration': 0}, 'private_settings': {}}


def scene(name, sources):
    items = [item(s, n, **place) for n, (s, place) in enumerate(sources, 1)]
    return source('scene', name, {'id_counter': len(items), 'custom_size': False, 'items': items},
                  mixers=0, canvas_uuid=CANVAS)


# OBS 先开、主播程序后开时，浏览器源第一次加载失败就再也不重试。所以每个源先打开一个本地等待页：
# 每 2 秒探一下主播程序，连上了再跳到真正的页面。页面加载以后主播程序重启，页面自己会重连。
WAIT_PAGE = """<!doctype html><meta charset="utf-8"><title>等主播程序</title>
<body style="margin:0;background:transparent"><script>
const host = 'http://127.0.0.1:{port}';
async function go() {{
  try {{ await fetch(host + '/health', {{mode: 'no-cors', cache: 'no-store'}}); location.replace(host + '/overlay/{page}/'); }}
  catch (e) {{ setTimeout(go, 2000); }}
}}
go();
</script>
"""


def windows_path(path):
    # 从 WSL 跑时 /mnt/e/... 要换成 E:\...，OBS 是 Windows 程序。
    parts = Path(path).resolve().parts
    if len(parts) > 2 and parts[1] == 'mnt' and len(parts[2]) == 1:
        return str(PureWindowsPath(f'{parts[2].upper()}:\\', *parts[3:]))
    return str(Path(path).resolve())


def browser(name, page, port, audio=False):
    wait = ROOT / 'runtime' / 'obs' / f'{page}.html'
    wait.parent.mkdir(parents=True, exist_ok=True)
    wait.write_text(WAIT_PAGE.format(port=port, page=page), encoding='utf-8')
    return source('browser_source', name, {'is_local_file': True, 'local_file': windows_path(wait),
                                           'width': 1920, 'height': 1080, 'fps_custom': False,
                                           'reroute_audio': audio, 'shutdown': False, 'restart_when_active': False},
                  mixers=255 if audio else 0, monitoring_type=2 if audio else 0)  # 她的声音：推流 + 本机监听


def collection(cfg):
    game, delay = cfg['overlay']['game'], float(cfg['overlay'].get('game_delay_seconds') or 0)
    capture = source('game_capture', '游戏采集', {'capture_mode': 'window', 'window': GAME_WINDOW, 'priority': 2,
                                                'capture_cursor': False, 'capture_audio': False}, mixers=0)
    sound = source('wasapi_process_output_capture', '游戏声音', {'window': GAME_WINDOW, 'priority': 2},
                   sync=int(delay * 1e9))
    port = cfg['server']['port']
    pages = [browser('舞台背景', 'stage', port), browser('状态卡', 'status', port),
             browser('弹幕', 'danmaku', port), browser('字幕', 'subtitle', port),
             browser('形象（她的声音）', 'avatar', port, audio=True)]
    frame = {'x': game['left'], 'y': game['top'], 'box': (game['width'], game['height'])}
    extra, sources = {}, [capture]
    if delay:
        # 要延迟：游戏采集放进“游戏原画”，虚拟摄像机输出它，正式场景接回来再挂异步延迟滤镜。
        raw = scene(RAW, [(capture, {'box': (1920, 1080)})])
        delayed = source('dshow_input', '游戏画面（延迟）', {'video_device_id': 'OBS Virtual Camera:', 'res_type': 0,
                                                        'active': True, 'deactivate_when_not_showing': False}, mixers=0,
                         filters=[source('async_delay_filter', '视频延迟（异步）', {'delay_ms': int(delay * 1000)}, mixers=0)])
        sources += [raw, delayed]
        shown = delayed
        extra = {'virtual-camera': {'type2': 1, 'scene': RAW}}  # 1 = 输出指定场景
    else:
        shown = capture  # 不延迟（先说后打）：游戏采集直接放进画框
    main = scene(STAGE, [(shown, frame), (sound, {})] + [(p, {}) for p in pages])
    order = [{'name': STAGE}] + ([{'name': RAW}] if delay else [])
    return {'name': NAME, 'sources': [*sources, sound, *pages, main], 'groups': [],
            'scene_order': order, 'current_scene': STAGE, 'current_program_scene': STAGE,
            'current_transition': '淡入淡出', 'transition_duration': 300, 'transitions': [],
            **extra, 'modules': {}}


def backup(path):
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}'))


def profile(obs_dir):
    """新建（或更新）同名配置文件：画布和输出都是 1920x1080 60 帧，其余照抄最近用的配置。"""
    folder = obs_dir / 'basic' / 'profiles' / NAME
    ini = configparser.ConfigParser(interpolation=None)
    ini.optionxform = str
    fresh = not folder.exists()
    if fresh:
        others = sorted((p for p in folder.parent.glob('*/basic.ini')), key=lambda p: p.stat().st_mtime)
        folder.mkdir(parents=True)
        if others:
            for f in others[-1].parent.iterdir():
                if f.name in ('basic.ini', 'streamEncoder.json', 'recordEncoder.json'):
                    shutil.copy2(f, folder / f.name)
    path = folder / 'basic.ini'
    if path.exists():
        if not fresh:
            backup(path)
        ini.read(path, encoding='utf-8-sig')
    for section, values in {'General': {'Name': NAME},
                            'Video': {'BaseCX': '1920', 'BaseCY': '1080', 'OutputCX': '1920', 'OutputCY': '1080',
                                      'FPSType': '0', 'FPSCommon': '60'}}.items():
        if not ini.has_section(section):
            ini.add_section(section)
        for key, value in values.items():
            ini[section][key] = value
    with open(path, 'w', encoding='utf-8-sig', newline='\r\n') as f:
        ini.write(f, space_around_delimiters=False)
    return path


def launcher(exe, delay):
    text = ('@echo off\r\nchcp 65001 >nul\r\n'
            'rem 用大肥鱼的配置和场景打开 OBS；画面要延迟时顺便开虚拟摄像机（延迟靠它）。\r\n'
            f'cd /d "{PureWindowsPath(exe).parent}"\r\n'
            f'start "" obs64.exe --profile "{NAME}" --collection "{NAME}"{" --startvirtualcam" if delay else ""}\r\n')
    (ROOT / 'obs.bat').write_text(text, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--obs-dir', default=os.path.join(os.environ.get('APPDATA', ''), 'obs-studio'))
    parser.add_argument('--obs-exe', default=next((p for p in OBS_EXES if Path(p).exists()), OBS_EXES[0]))
    args = parser.parse_args()
    obs_dir = Path(args.obs_dir)
    if not (obs_dir / 'basic').is_dir():
        sys.exit(f'没找到 OBS 配置目录：{obs_dir}（先打开过一次 OBS，或用 --obs-dir 指定）')
    cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
    scenes = obs_dir / 'basic' / 'scenes' / f'{NAME}.json'
    backup(scenes)
    scenes.write_text(json.dumps(collection(cfg), ensure_ascii=False, indent=1), encoding='utf-8')
    ini = profile(obs_dir)
    launcher(args.obs_exe, cfg['overlay'].get('game_delay_seconds'))
    print(f'场景集合：{scenes}\n配置文件：{ini}\n启动脚本：{ROOT / "obs.bat"}\n'
          f'游戏画面和游戏声音延迟 {cfg["overlay"].get("game_delay_seconds") or 0} 秒')


if __name__ == '__main__':
    main()
