"""程序化几何 Rig 测试素材；不是正式美术，不调用生图/付费接口。Python 标准库即可。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'overlay/avatar/packs/rig-test'
OUT.mkdir(parents=True, exist_ok=True)
parts = []


def svg(name, rect, body):
    x, y, w, h = rect
    path = f'{name}.svg'
    (OUT / path).write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{x} {y} {w} {h}">{body}</svg>\n', encoding='utf-8')
    return path


def ellipse(cx, cy, rx, ry, fill, stroke='none', sw=8):
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'


def path(d, fill, stroke='none', sw=10):
    return f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round"/>'


def part(name, rect, body, z, parent='head', pivot=None, mesh=(6, 8), depth=.5, deformers=('face',), **extra):
    p = dict(id=name, parent=parent, image=svg(name, rect, body), rect=rect, z=z, pivot=pivot or [rect[0]+rect[2]/2, rect[1]+rect[3]/2], mesh=list(mesh), depth=depth, deformers=list(deformers), **extra)
    parts.append(p)
    return p


part('backHair', [440, 520, 1168, 2200], path('M490 2550 Q400 1400 560 830 Q700 470 1030 550 Q1430 500 1550 850 L1570 2560 Q1430 2650 1280 2510 L1050 2670 L820 2500 Q650 2670 490 2550Z', '#405599', '#223969'), 0, pivot=[1024,700], depth=-.45, deformers=('face','hair'), physics='hair', weights={'axis':'y','from':700,'to':2620,'power':1.5}, mesh=(10,16))
part('body', [470, 1680, 1108, 1392], path('M500 3072 L530 2110 Q540 1800 840 1780 L1200 1780 Q1510 1800 1530 2110 L1560 3072Z', '#79cadb', '#285a82')+path('M840 1800 L1024 2130 L1200 1800 L1320 1870 L1160 2340 L870 2340 L720 1870Z', '#f4fbff', '#4976a0')+path('M650 2420 L1380 2420 L1450 3072 L590 3072Z', '#3c75ad'), 10, parent='body', pivot=[1024,3072], deformers=('breath',), mesh=(12,14), depth=0)
part('neck', [840, 1470, 370, 480], path('M880 1490 L1160 1490 L1180 1820 Q1030 1950 860 1820Z', '#f7cfb6', '#c58f88'),20,parent='body',pivot=[1024,1850],deformers=('breath',),depth=0)
part('face',[570,580,910,1150],ellipse(1024,1150,430,550,'#ffe0c9','#c58f88'),30,pivot=[1024,1700],mesh=(12,12),depth=.25)
for side, x in [('L',770),('R',1278)]:
    part(f'blush{side}',[x-115,1260,230,140],ellipse(x,1330,100,55,'#ff839f'),40,opacityParam='blush',depth=.55)
    eye_rect=[x-170,1020,340,280]
    side_name='left' if side=='L' else 'right'
    eye=part(f'eyeWhite{side}',eye_rect,ellipse(x,1160,152,116,'#fffdfa'),50,role='eyeWhite',side=side_name,depth=.6,mesh=(6,4))
    eye['variants']={'open':eye['image'],'half':svg(f'eyeWhite{side}-half',eye_rect,path(f'M{x-150} 1150 L{x+150} 1150 Q{x+140} 1270 {x} 1270 Q{x-140} 1270 {x-150} 1150Z','#fffdfa')),'closed':svg(f'eyeWhite{side}-closed',eye_rect,'')}
    part(f'iris{side}',[x-100,1030,200,260],ellipse(x,1160,87,112,'#2976a9','#22386f')+ellipse(x,1160,42,78,'#173553'),51,role='pupil',side=side_name,mask=eye['id'],depth=.65,mesh=(4,4))
    part(f'highlight{side}',[x-80,1050,160,200],ellipse(x-27,1100,26,38,'#fff')+ellipse(x+35,1200,14,18,'#d2ffff'),52,role='highlight',side=side_name,mask=eye['id'],depth=.65,mesh=(2,2))
    lid=part(f'lid{side}',eye_rect,path(f'M{x-160} 1160 Q{x} 920 {x+160} 1160','none','#293152',18),53,role='eyelid',side=side_name,depth=.65,mesh=(6,4))
    lid['variants']={'open':lid['image'],'half':svg(f'lid{side}-half',eye_rect,path(f'M{x-160} 1145 Q{x} 1120 {x+160} 1145','none','#293152',20)),'closed':svg(f'lid{side}-closed',eye_rect,path(f'M{x-150} 1160 Q{x} 1270 {x+150} 1160','none','#293152',20))}
    rect=[x-180,880,360,190]
    brow=part(f'brow{side}',rect,path(f'M{x-130} 1000 Q{x} 945 {x+130} 1000','none','#664e84',24),75,role='brow',side=side_name,opacity=.7,depth=.65,mesh=(4,2))
    brow['variants']={}
    for em, left, mid, right in [('neutral',1000,945,1000),('happy',1000,900,990),('excited',960,890,950),('surprised',940,900,940),('sad',1010,950,940),('angry',940,975,1020)]:
        if side=='R': left,right=right,left
        brow['variants'][em]=svg(f'brow{side}-{em}',rect,path(f'M{x-130} {left} Q{x} {mid} {x+130} {right}','none','#664e84',24))
rect=[844,1370,360,280]
mouth=part('mouth',rect,'',61,role='mouth',pivot=[1024,1480],depth=.7,mesh=(6,4))
mouth['variants']={}
for variant in ['', 'smile', 'happy', 'angry']:
    for key, rx, ry in [('N',90,0),('half',75,42),('A',103,95),('I',120,35),('U',45,65),('E',108,68),('O',65,95)]:
        if key=='N':
            mid=1530 if variant in ('smile','happy') else 1440 if variant=='angry' else 1490
            body=path(f'M934 1480 Q1024 {mid} 1114 1480','none','#984e69',14)
        else:
            body=ellipse(1024,1480,rx,ry,'#71354e','#b1667e')
            if variant=='happy': body+=path(f'M{1024-rx+12} {1480-ry+12} Q1024 {1480-ry-5} {1024+rx-12} {1480-ry+12} L{1024+rx-18} {1480-ry+35} L{1024-rx+18} {1480-ry+35}Z','#fff9f1')
            else: body+=ellipse(1024,1480+ry*.45,rx*.65,ry*.3,'#f0a0ad')
        name=f'{variant}.{key}' if variant else key
        mouth['variants'][name]=svg(f'mouth-{name}',rect,body)
mouth['image']=mouth['variants']['N']
part('frontHair',[520,480,1010,650],path('M550 900 Q540 500 1010 510 Q1440 490 1500 900 L1360 1060 L1260 790 L1120 1050 L1000 780 L830 1090 L770 840 L600 1070Z','#889bc8','#425586'),70,pivot=[1024,600],depth=.8,deformers=('face','hair'),physics='hair',weights={'axis':'y','from':600,'to':1100,'power':1.8},mesh=(10,10))
for side,x in [('L',540),('R',1400)]:
    part(f'sideHair{side}',[x-120,780,300,1450],path(f'M{x-60} 820 Q{x+100} 740 {x+125} 1000 L{x+140} 2130 L{x+20} 2010 L{x-90} 2190 L{x-110} 1210Z','#7d91c6','#425586'),71,pivot=[x,850],depth=.5,deformers=('face','hair'),physics=f'side{side}',weights={'axis':'y','from':850,'to':2190,'power':1.6},mesh=(6,14))
part('ahoge',[920,180,430,500],path('M1030 620 Q940 330 1220 250 Q1120 380 1130 590Z','#9bb9df','#425586'),72,pivot=[1070,620],depth=.4,deformers=('face','hair'),physics='ahoge',weights={'axis':'y','from':620,'to':240,'power':1.2},mesh=(4,10))
part('ornament',[1250,600,390,400],path('M1290 800 L1420 640 L1580 790 L1440 960Z','#8de5e9','#e1bb64',20),80,pivot=[1370,740],depth=.8,deformers=('face','hair'),physics='ornament',mesh=(4,4))
for side,x in [('L',1360),('R',1510)]:
    part(f'ribbon{side}',[x-70,850,180,650],path(f'M{x-40} 880 L{x+50} 880 L{x+80} 1470 L{x} 1380 L{x-50} 1480Z','#ead3ec','#9e86bc'),81,pivot=[x,880],depth=.7,deformers=('face','hair'),physics='ribbon',weights={'axis':'y','from':880,'to':1480,'power':1.3},mesh=(4,10))
part('whaleClip',[420,700,390,300],ellipse(590,840,135,90,'#87e4f5','#2d729a')+path('M690 840 L780 760 L770 890Z','#87e4f5','#2d729a')+ellipse(530,820,13,13,'#184369')+path('M570 740 Q530 670 490 710 M570 740 Q610 660 650 700','none','#b5f2fa',14),82,pivot=[610,810],depth=.9,deformers=('face','hair'),physics='ornament',mesh=(4,4))
part('tassel',[1480,930,220,880],path('M1510 960 L1590 1040 L1510 1120 L1490 1040Z','#3987d8','#e4be68',14)+''.join(path(f'M1545 1110 Q{1520+i*20} 1400 {1500+i*25} 1770','none',['#4c9ed2','#6bd6e4','#78bce8'][i%3],20) for i in range(6)),83,pivot=[1545,1010],depth=.8,deformers=('face','hair'),physics='tassel',weights={'axis':'y','from':1010,'to':1770,'power':1.3},mesh=(6,14))
part('chestBow',[670,1920,700,430],path('M1024 2100 Q720 1850 700 2020 L730 2310 Q920 2260 1024 2150 Q1200 2310 1320 2280 L1340 2010 Q1270 1860 1024 2100Z','#26364d','#172234')+ellipse(1024,2120,85,95,'#4fbce4','#e7c779',16),31,parent='body',pivot=[1024,2070],depth=.2,deformers=('breath','hair'),physics='bow',weights={'axis':'y','from':2030,'to':2350},mesh=(8,6))


def chain(k,d,angle,drive,segments=3):
    return dict(segments=segments,stiffness=k,damping=d,mass=1,maxAngle=angle,drive=drive)


pack={
    'version':1,'_testOnly':'程序绘制几何测试素材，不是正式小鲸鱼美术；无模型生图、无外部依赖。',
    'credit':'RIG TEST · 程序几何测试素材 / 非正式美术',
    'canvas':dict(width=2048,height=3072,anchorX=1024,anchorY=3072,charHeight=2850),
    'groups':[
        dict(id='root',pivot=[1024,3072],bindings=dict(x=dict(param='bodyX',gain=1),y=dict(param='bodyY',gain=1))),
        dict(id='body',parent='root',pivot=[1024,2900],bindings=dict(rotation=dict(param='bodyRoll',gain=1))),
        dict(id='head',parent='body',pivot=[1024,1740],bindings=dict(rotation=dict(param='roll',gain=10),y=dict(param='pitch',gain=32))),
    ],
    'render':dict(pixelRatio=1,padding=180,rim=dict(enabled=True,color=[.2,.65,1],width=2,strength=.5)),
    'physics':{
        'hair':chain(65,9,20,dict(roll=12,yaw=6,bodyX=.1)),
        'sideL':chain(58,8,24,dict(roll=15,yaw=7,bodyY=.12),4),
        'sideR':chain(68,9,22,dict(roll=12,yaw=6,bodyY=.10),4),
        'ahoge':chain(55,6,30,dict(roll=18,pitch=10),3),
        'ornament':chain(110,12,12,dict(roll=8,yaw=5),2),
        'ribbon':chain(40,7,28,dict(roll=16,yaw=9),4),
        'tassel':chain(27,4,35,dict(roll=20,yaw=12,bodyY=.14),5),
        'bow':chain(85,11,8,dict(bodyRoll=1,bodyY=.08,breath=.5),2),
    },
    'emotions':{'happy':{'mouthVariant':'happy'},'excited':{'mouthVariant':'happy'}},
    'parts':parts,
}
(OUT/'rig.json').write_text(json.dumps(pack,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Rig 几何测试包：{len(parts)} 部件，{len(list(OUT.glob("*.svg")))} SVG；{OUT}')
