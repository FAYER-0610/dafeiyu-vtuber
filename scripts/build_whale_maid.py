"""小鲸鱼正式包：本地母版修复、手工语义遮罩、遮挡补全、统一差分裁切。
不覆盖 final-03-ext.png，不调用生成接口。使用 python3 -I 执行。
"""
from pathlib import Path
import json
import hashlib
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage
from scipy.interpolate import PchipInterpolator

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT.parent / 'avatar-original'
MASTER = ART / 'master/final-03-ext.png'
OUT = ROOT / 'overlay/avatar/packs/whale-maid'
PROOF = ROOT.parent / '.preview/whale-maid'
OUT.mkdir(parents=True, exist_ok=True)
PROOF.mkdir(parents=True, exist_ok=True)
W, H = 1024, 1536
src = np.array(Image.open(MASTER).convert('RGBA'))
assert src.shape == (H, W, 4)
master_hash = hashlib.sha256(MASTER.read_bytes()).hexdigest()


def polygon(points):
    m = np.zeros((H, W), np.uint8)
    cv2.fillPoly(m, [np.array(points, np.int32)], 255)
    return m.astype(np.float32) / 255


def ellipse(x, y, rx, ry):
    yy, xx = np.mgrid[:H, :W]
    return np.maximum(0, 1-((xx-x)/rx)**2-((yy-y)/ry)**2).astype(np.float32)


def rectangle(x0,y0,x1,y1):
    m=np.zeros((H,W),np.float32);m[y0:y1,x0:x1]=1;return m


def blur(m, sigma):
    return cv2.GaussianBlur(m.astype(np.float32),(0,0),sigma) if sigma else m


def clean_master():
    a=src.copy();alpha=a[:,:,3].astype(np.float32)
    # 游离半透明残影：仅清理指定外缘且距实心线稿超过3px的低alpha像素，保留抗锯齿。
    opaque=alpha>=246
    distance=ndimage.distance_transform_edt(~opaque)
    roi=rectangle(40,865,126,1008)+rectangle(900,875,1013,1160)
    ghost=(roi>0)&(alpha<100)&(distance>3)
    alpha[ghost]=0
    # 残影有不透明描边；只按alpha阈值会留下孤立三角，故以手工轮廓整体清掉。
    ghost_shape=np.maximum(polygon([(54,980),(99,984),(116,932),(140,866),(124,869),(59,946)]),polygon([(92,974),(112,976),(122,989),(120,993),(94,993)]))
    dark_edge=(np.max(a[:,:,:3],axis=2)<170)&(a[:,:,2].astype(int)-a[:,:,0].astype(int)<45)
    alpha*=1-blur(ghost_shape,0.65)*dark_edge
    count,labels,stats,_=cv2.connectedComponentsWithStats((alpha>24).astype(np.uint8),8)
    tiny=np.zeros(count,bool);tiny[1:]=stats[1:,cv2.CC_STAT_AREA]<65
    edgeROI=(rectangle(30,850,150,1020)+rectangle(890,875,1015,1180))>0
    alpha[tiny[labels]&edgeROI]=0
    solidDistance=ndimage.distance_transform_edt(alpha<225)
    alpha[edgeROI&(alpha<155)&(solidDistance>2.2)]=0
    # 仅修正低频色差；保留原始高频发丝/轮廓，不在细线交叉处使用窄带inpaint。
    rgb=a[:,:,:3].astype(np.float32);low=cv2.GaussianBlur(rgb,(0,0),12)
    yy,xx=np.mgrid[:H,:W]
    for x,y0 in [(92,1005),(932,900)]:
        weight=np.maximum(0,1-np.abs(xx-x)/32)**2
        weight*=np.clip((yy-y0)/35,0,1)*(alpha>245)*(rgb[:,:,2]-rgb[:,:,0]>18)
        left=low[:,x-32:x-31];right=low[:,x+32:x+33]
        mix=np.clip((xx-x+32)/64,0,1)[:,:,None]
        target=left*(1-mix)+right*mix
        delta=np.clip(target-low,-7,7)*0.65
        rgb+=delta*weight[:,:,None]
    a[:,:,:3]=rgb.round().clip(0,255).astype(np.uint8);a[:,:,3]=alpha.clip(0,255).astype(np.uint8)
    a[(a[:,:,3]==0)&(src[:,:,3]>0),:3]=0
    # 修复区域绝不覆盖正式差分的脸部区域（包含前景RGB和alpha）。
    assert np.array_equal(a[726:916,268:790],src[726:916,268:790])
    assert np.array_equal(a[890:985,460:590],src[890:985,460:590])
    Image.fromarray(a).save(ART/'master/final-03-clean.png')
    bg=np.zeros_like(a);bg[:]=[22,42,70,255]
    before=Image.alpha_composite(Image.fromarray(bg),Image.fromarray(src)).convert('RGB')
    after=Image.alpha_composite(Image.fromarray(bg),Image.fromarray(a)).convert('RGB')
    boxes=[('left ghost',(38,850,168,1020)),('left seam',(55,1110,135,1480)),('right seam',(895,980,975,1400))]
    for name,box in boxes:
        w=(box[2]-box[0])*3;h=(box[3]-box[1])*3
        proof=Image.new('RGB',(w*2+12,h+30),(20,29,46));dr=ImageDraw.Draw(proof)
        proof.paste(before.crop(box).resize((w,h)),(0,30));proof.paste(after.crop(box).resize((w,h)),(w+12,30))
        dr.text((5,8),'BEFORE',fill='white');dr.text((w+17,8),'AFTER',fill='white')
        proof.save(PROOF/(name.replace(' ','-')+'-compare.png'))
    after.save(PROOF/'master-clean-on-blue.png')
    return a


clean=clean_master()
if __name__=='__main__':
    print('母版修复完成；原图 SHA256',master_hash)

# 所有遮罩均以原生画布坐标定义；PNG只裁切透明边界，不重采样。
rgb=clean[:,:,:3].astype(np.float32);alpha=clean[:,:,3]/255.
yy,xx=np.mgrid[:H,:W]
blue=(rgb[:,:,2]-rgb[:,:,0]>18)&(rgb[:,:,2]-rgb[:,:,1]>3)
jawCurve=PchipInterpolator([285,351,430,519,608,685,742],[967,994,1014,1020,1013,995,967],extrapolate=True)(xx)
jawBand=(xx>350)&(xx<720)&(np.abs(yy-jawCurve)<5)
parts=[];art={};missing=[]
sourceRGB=rgb.copy()

def grow(mask,n):
    return cv2.dilate(mask.astype(np.float32),np.ones((n*2+1,n*2+1),np.uint8))

def extension(image, known, support, softness=1):
    """从同一语义部件的邻近纹理延伸遮挡边，不借用相邻部件的颜色。"""
    valid=known>0.7
    indices=ndimage.distance_transform_edt(~valid,return_distances=False,return_indices=True)
    extended=image[indices[0],indices[1]].copy()
    if softness:
        soft=cv2.GaussianBlur(extended.astype(np.float32),(0,0),softness)
        extended=np.where(valid[:,:,None],image,soft)
    return extended, support


def save_asset(name,image,mask,rect=None):
    if rect is None:
        ys,xs=np.nonzero(mask>0.002)
        assert len(xs),name
        x0=max(0,int(xs.min())-2);y0=max(0,int(ys.min())-2)
        x1=min(W,int(xs.max())+3);y1=min(H,int(ys.max())+3)
        rect=[x0,y0,x1-x0,y1-y0]
    x,y,w,h=rect
    rgba=np.dstack((image.clip(0,255).astype(np.uint8),(np.clip(mask,0,1)*255).round().astype(np.uint8)))
    rgba[rgba[:,:,3]==0,:3]=0
    Image.fromarray(rgba[y:y+h,x:x+w]).save(OUT/(name+'.png'))
    art[name]=rgba
    return rect


def add(name,mask,z,image=rgb,parent='head',depth=.2,physics=None,pivot=(520,850),rect=None,role=None,side=None,variants=None,opacity=1,deformers=None,weights=None):
    rect=save_asset(name,image,mask,rect)
    p=dict(id=name,parent=parent,image=name+'.png',rect=rect,z=z,pivot=list(pivot),mesh=[12,12],depth=depth,deformers=deformers if deformers is not None else ['face'])
    if physics:p.update(physics=physics,deformers=['face','hair'],weights=weights or {'axis':'y','from':pivot[1],'to':max(pivot[1]+50,rect[1]+rect[3]),'power':1.5})
    if role:p['role']=role
    if side:p['side']=side
    if variants:p['variants']=variants
    if opacity!=1:p['opacity']=opacity
    parts.append(p)
    return p

# 配饰按真实外轮廓切出；其下的发色将在后续语义补全中重建。
ahoge=polygon([(345,383),(347,345),(388,305),(431,285),(474,290),(506,307),(528,351),(534,400),(525,447),(501,452),(505,389),(491,350),(465,335),(430,336),(384,359)])*alpha
ahoge=np.maximum(ahoge,rectangle(320,260,560,416)*blue*alpha)
whale=polygon([(729,701),(736,683),(756,668),(774,667),(767,657),(765,647),(772,641),(779,644),(785,658),(791,645),(800,646),(802,651),(802,658),(795,669),(808,681),(816,700),(815,711),(821,706),(826,708),(829,716),(825,723),(816,726),(809,735),(795,742),(794,749),(785,754),(779,751),(775,745),(757,742),(741,731),(732,718)])
tassel=polygon([(822,660),(829,659),(839,669),(852,683),(861,705),(858,731),(865,736),(874,753),(867,765),(885,795),(914,810),(912,818),(886,833),(858,834),(852,785),(845,751),(844,735),(831,721),(824,703)])
ribbonLdomain=polygon([(246,525),(183,539),(161,582),(180,616),(143,631),(129,651),(141,680),(112,737),(98,791),(120,813),(97,885),(91,987),(144,1009),(159,986),(154,1053),(207,1076),(229,922),(244,690)])
ribbonRdomain=polygon([(791,562),(844,577),(843,630),(827,651),(864,688),(920,717),(886,774),(879,840),(901,951),(882,1008),(841,1000),(824,850),(817,733),(788,643)])
dark=(np.max(rgb,axis=2)<145)&(rgb[:,:,2]-rgb[:,:,0]<45)
ribbonL=blur((ribbonLdomain*dark).astype(np.float32),.45)*alpha
ribbonR=blur((ribbonRdomain*dark).astype(np.float32),.45)*alpha*(1-tassel)
# 荷叶边和黑色发箍的轮廓域；蓝色长发留给头发部件。
headdressDomain=polygon([(84,840),(97,805),(100,763),(100,718),(129,690),(144,626),(191,616),(211,561),(231,527),(261,475),(305,460),(311,433),(348,408),(391,393),(409,369),(455,360),(493,360),(529,363),(557,379),(577,362),(620,365),(660,385),(661,410),(706,413),(754,442),(761,475),(779,486),(793,484),(827,520),(830,552),(847,590),(883,627),(884,661),(878,690),(914,781),(939,811),(929,844),(886,877),(859,890),(833,852),(818,759),(792,617),(725,518),(613,440),(509,415),(399,449),(310,491),(242,575),(185,701),(155,889),(112,873)])
headdress=headdressDomain*alpha*(1-ribbonL)*(1-ribbonR)*(1-whale)*(1-tassel)*(1-ahoge)
chestDomain=polygon([(434,1050),(471,1052),(503,1065),(519,1057),(540,1068),(563,1054),(599,1061),(624,1074),(645,1092),(638,1130),(608,1150),(628,1185),(597,1221),(552,1198),(526,1159),(481,1222),(429,1189),(443,1155),(423,1123),(419,1086)])
chestBow=chestDomain*alpha
accessory=np.maximum.reduce([ahoge,whale,tassel,ribbonL,ribbonR,headdress,chestBow])
# 蓝发色域仅用于边界辅助；眼球和服装蓝宝石必须显式排除。
hair=blue.astype(np.float32)*alpha*(1-accessory)
eyeLeftInterior=polygon([(301,842),(319,806),(342,786),(376,777),(407,782),(431,803),(445,848),(442,879),(422,893),(369,901),(330,899),(310,882)])
eyeRightInterior=polygon([(601,800),(622,778),(653,766),(686,771),(714,791),(741,827),(747,855),(731,881),(701,891),(654,887),(620,883),(607,858)])
eyeInterior=grow(np.maximum(eyeLeftInterior,eyeRightInterior),5)
eyeArea=np.maximum(rectangle(264,735,478,920),rectangle(574,721,794,913))
hair*=1-eyeInterior
hair*=1-eyeArea*(rgb[:,:,2]-rgb[:,:,0]<60)
hair*=1-rectangle(450,1030,620,1536) # 中心服装上的蓝色小标记不属于头发。
hair=cv2.morphologyEx(hair,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))*alpha
# 极深发丝边线补入邻近发色内部，不能侵入肤色/白色荷叶边。
near=grow(hair,2)*(rgb[:,:,0]<140)*(rgb[:,:,2]-rgb[:,:,0]>8)*alpha*(1-accessory)
hair=np.maximum(hair,near)*(1-eyeInterior)
hair*=1-eyeArea*(rgb[:,:,2]-rgb[:,:,0]<60)
# 抗锯齿边只延入相邻深色线稿，不用全局阈值截断发梢。
hair=np.maximum(hair,grow(hair,1)*(rgb[:,:,0]<190)*(1-eyeArea)*(1-accessory))*alpha
hair*=~jawBand
frontDomain=polygon([(153,819),(159,698),(209,586),(305,482),(422,428),(511,413),(596,423),(698,476),(786,585),(828,727),(808,834),(754,836),(702,797),(639,771),(606,716),(607,826),(555,829),(501,800),(456,772),(429,730),(400,638),(365,699),(328,773),(289,815),(258,846),(192,850)])
front=hair*frontDomain
front=np.maximum(front,hair*rectangle(180,410,815,827))
leftDomain=polygon([(140,660),(251,577),(350,619),(340,739),(284,820),(289,907),(318,943),(364,948),(321,973),(355,975),(324,991),(350,1010),(342,1072),(362,1105),(395,1115),(352,1122),(366,1160),(406,1176),(361,1183),(390,1201),(344,1201),(306,1182),(258,1115),(209,1011),(166,927),(144,815)])
rightDomain=polygon([(757,616),(835,663),(857,785),(857,949),(822,1027),(792,1116),(743,1176),(693,1204),(655,1201),(683,1181),(647,1175),(685,1157),(672,1139),(721,1105),(714,1074),(733,1034),(746,977),(690,981),(721,959),(688,940),(737,923),(773,879),(777,800),(746,741)])
leftDomain=np.maximum(leftDomain,rectangle(145,805,415,1023))
rightDomain=np.maximum(rightDomain,rectangle(660,805,860,1023))
sideL=hair*leftDomain*(1-front);sideR=hair*rightDomain*(1-front)
rest=hair*(1-front)*(1-sideL)*(1-sideR)
longL=rest*rectangle(0,815,391,H);longR=rest*rectangle(660,715,W,H)
backVisible=rest*(1-longL)*(1-longR)
# 后脑和身体后面的遮挡部分由同一发色纹理延展，不保留母版五官/身体副本。
backSupport=np.maximum(backVisible,polygon([(213,660),(300,492),(477,440),(641,463),(795,645),(832,893),(803,1140),(786,1535),(243,1535),(218,1160),(183,898)]))
backRGB,_=extension(rgb,np.maximum(backVisible,np.maximum(longL,longR)),backSupport,12)
add('backHair',blur(backSupport,.6),1,backRGB,depth=-.3,physics='back',pivot=(516,575))
for name,mask,z,piv,chain,depth in [('longHairLeft',longL,2,(223,835),'longLeft',-.2),('longHairRight',longR,3,(820,740),'longRight',-.2)]:
    im,support=extension(rgb,mask,grow(mask,2),.65)
    add(name,blur(support,.5),z,im,depth=depth,physics=chain,pivot=piv)
# 身体去掉头发与蝴蝶结，局部扩展衣料覆盖肩部遮挡；手臂维持原生线稿。
bodyDomain=polygon([(349,1029),(454,1010),(578,1010),(700,1030),(730,1139),(768,1191),(817,1215),(831,1299),(825,1382),(790,1438),(818,1490),(863,1535),(178,1535),(218,1488),(240,1435),(198,1374),(191,1313),(207,1231),(260,1194),(305,1143)])
bodyKnown=bodyDomain*alpha*(1-sideL)*(1-sideR)*(1-chestBow)
bodyKnown*=~((xx>300)&(xx<742)&(yy<=jawCurve))
bodySupport=np.maximum(bodyKnown,polygon([(358,1040),(466,1020),(574,1020),(692,1045),(735,1189),(690,1315),(693,1535),(341,1535),(330,1280),(289,1195)]))
bodyRGB,_=extension(rgb,bodyKnown,bodySupport,8)
add('body',blur(bodySupport,.55),10,bodyRGB,parent='body',depth=0,pivot=(519,1375),deformers=['breath'])
neckSupport=polygon([(473,987),(561,987),(565,1024),(551,1047),(531,1061),(514,1056),(500,1045),(482,1025)])
neckKnown=neckSupport*(rgb[:,:,0]>180)*(rgb[:,:,0]-rgb[:,:,2]>12)*rectangle(0,1007,W,1060)
neckRGB,_=extension(rgb,neckKnown,neckSupport,5)
add('neck',blur(neckSupport,.8),9,neckRGB,parent='body',depth=.05,pivot=(520,1048),deformers=['breath'])
# 不含五官的脸：对未遮挡肤色拟合低阶光照；只在五官/刘海隐藏区使用补绘。
faceSupport=polygon([(203,855),(225,767),(309,697),(369,622),(410,592),(466,610),(596,574),(694,694),(763,758),(794,850),(783,916),(742,967),(685,995),(608,1013),(519,1020),(430,1014),(351,994),(285,967),(243,934),(220,925),(196,915)])
# 下颌沿母版肤色/描边确定真实弧线，上半脸继续向发后补全。
jawMatte=np.clip((jawCurve-yy+.55)/1.1,0,1)
faceSupport=np.where((xx>285)&(xx<742)&(yy>947),jawMatte,faceSupport)
feature=grow(np.maximum(eyeLeftInterior,eyeRightInterior),19)+np.clip(ellipse(524,940,65,46)*4,0,1)
feature+=rectangle(299,669,466,722)+rectangle(581,652,739,714)
feature+=np.minimum(1,ellipse(354,918,92,45)*3)+np.minimum(1,ellipse(687,908,91,45)*3)
skin=(rgb[:,:,0]>80)&(rgb[:,:,0]-rgb[:,:,2]>4)
known=(faceSupport>.9)&skin&(feature<.1)
faceRGB=np.empty_like(rgb);faceRGB[:]=[255,244,232]
faceRGB[:,:,1]+=np.clip((850-yy)/120,-2,2);faceRGB[:,:,2]+=np.clip((850-yy)/65,-4,4)
preserve=blur(known.astype(np.float32),3)*skin
faceRGB=faceRGB*(1-preserve[:,:,None])+rgb*preserve[:,:,None]
# 原分割边上的零散深色像素不保留为颌缘；以连续柔和原色曲线收边。
jawZone=(xx>300)&(xx<731)&(np.abs(yy-jawCurve)<6)
jawBase=np.empty_like(rgb);jawBase[:]=[255,242,229]
lineWeight=np.exp(-((yy-jawCurve+.7)/.65)**2)*.65
jawBase=jawBase*(1-lineWeight[:,:,None])+np.array([137,95,93])*lineWeight[:,:,None]
faceRGB=np.where(jawZone[:,:,None],jawBase,faceRGB)
# 鼻尖是脸上固有的极细短线，不参与嘴型替换。
nose=blur(rectangle(513,870,522,880),1)
faceRGB=faceRGB*(1-nose[:,:,None])+rgb*nose[:,:,None]
add('face',blur(faceSupport,.7),20,faceRGB,depth=.55,pivot=(521,852))
for side,cx,cy in [('Left',354,918),('Right',687,908)]:
    mask=np.minimum(1,ellipse(cx,cy,88,38)*2.5)*faceSupport*skin*(1-grow(eyeInterior,7))
    p=add('blush'+side,mask,24,rgb,depth=.56)
    p['opacityParam']='blush'
# 胸针整体固定在胸前但有独立小幅物理；补全衣料隐藏在其后。
add('chestBow',blur(chestBow,.45),30,rgb,parent='body',depth=0,physics=None,pivot=(526,1085),deformers=['breath','hair'])
parts[-1].update(physics='chest',weights={'axis':'y','from':1068,'to':1220,'power':1.6})
add('headdress',blur(headdress,.45),40,rgb,depth=.35,pivot=(519,490))
add('ribbonLeft',ribbonL,44,rgb,depth=.12,physics='ribbonLeft',pivot=(222,599))
add('ribbonRight',ribbonR,45,rgb,depth=.12,physics='ribbonRight',pivot=(820,615))

# 眼睛：开口alpha同时作为真实变形stencil。虹膜补圆，白色高光另层。
eye_specs=[('left',[264,735,214,185],(385,842,55,65),[(301,842),(319,806),(342,786),(376,777),(407,782),(431,803),(445,848),(442,879),(422,893),(369,901),(330,899),(310,882)],[(265,846),(286,828),(302,789),(331,766),(365,749),(399,752),(430,768),(455,794),(468,850),(452,887),(430,906),(384,915),(329,914),(302,898),(282,879)]),('right',[574,721,220,192],(662,830,57,66),[(601,800),(622,778),(653,766),(686,771),(714,791),(741,827),(747,855),(731,881),(701,891),(654,887),(620,883),(607,858)],[(575,801),(597,773),(623,746),(658,733),(691,736),(722,752),(743,779),(763,801),(782,821),(767,848),(755,879),(732,900),(690,907),(640,899),(609,890),(589,859)])]
variants_dir=ART/'variants'

def variant_image(key):
    path=variants_dir/(key+'.png')
    if path.exists():
        a=np.array(Image.open(path).convert('RGBA'));assert a.shape==src.shape
        return a[:,:,:3].astype(np.float32)
    missing.append(key)
    return rgb.copy()

for side,rect,(cx,cy,rx,ry),opening_points,domain_points in eye_specs:
    suffix=side.title();opening=polygon(opening_points);domain=polygon(domain_points)
    versions={'open':rgb,'half':variant_image('eyes_half'),'closed':variant_image('eyes_closed'),'happy':variant_image('eyes_happy'),'teary':variant_image('eyes_teary'),'star':variant_image('eyes_star'),'dizzy':variant_image('eyes_dizzy')}
    whites={};lids={}
    for state,v in versions.items():
        colorful=(v[:,:,2]-v[:,:,0]>52)&(v[:,:,2]-v[:,:,1]>8)
        white=(v[:,:,2]>v[:,:,0]*.94)&(v[:,:,1]>v[:,:,0]*.92)&(v[:,:,0]>165)
        om=(opening*((colorful|white))).astype(np.float32)
        om=cv2.morphologyEx(om,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        if state in ['closed','happy']:om[:]=0
        if state=='half':
            if not (variants_dir/'eyes_half.png').exists():om*=np.clip((yy-(cy-12))/5,0,1)
            else:
                # 半睁后的上眼皮肤高光不是眼白：以厚睫毛最大连通域下缘封住stencil。
                dark=(domain*(v[:,:,0]<145)*(v[:,:,1]<135)*(v[:,:,2]-v[:,:,0]<60)).astype(np.uint8)
                n,labels,stats,_=cv2.connectedComponentsWithStats(dark,8)
                if n>1:
                    lid=labels==(1+np.argmax(stats[1:,cv2.CC_STAT_AREA]))
                    cols=np.flatnonzero(lid.any(axis=0))
                    bottom=np.array([np.flatnonzero(lid[:,x])[-1] for x in cols])
                    boundary=ndimage.gaussian_filter1d(np.interp(np.arange(W),cols,bottom),1.2)
                    om*=np.clip((yy-boundary[None,:]+.5)/1.5,0,1)
        om=blur(om,.4)*(1-grow(front,1))
        whiteRGB=np.empty_like(rgb);whiteRGB[:]=[246,246,250]
        whiteRGB=np.where(white[:,:,None],v,whiteRGB)
        if state in ['teary','star','dizzy']:
            # 特殊眼包含完整虹膜图案；沿母版眼开口裁切，原虹膜/高光由表情显式隐藏。
            om=art['eyeWhite'+suffix+'-open'][:,:,3]/255.
            whiteRGB=v
        wname='eyeWhite'+suffix+'-'+state;save_asset(wname,whiteRGB,om,rect);whites[state]=wname+'.png'
        line=(v[:,:,0]<210)&(v[:,:,1]<180)&(v[:,:,2]-v[:,:,0]<60)
        crease=(v[:,:,0]-v[:,:,1]>18)&(v[:,:,1]-v[:,:,2]>1)&(v[:,:,0]<242)&(yy<cy-30)
        lidmask=blur((domain*(line|crease)*(1-om)).astype(np.float32),.35)*(1-grow(front,1))
        if state=='teary':
            tearTint=(v[:,:,2]-v[:,:,0]>22)&(v[:,:,2]-v[:,:,1]>7)
            lidmask=np.maximum(lidmask,blur((domain*tearTint*(1-om)).astype(np.float32),.35)*(1-grow(front,1)))
        if state=='closed' and not (variants_dir/'eyes_closed.png').exists():
            # 明确临时占位，不把自绘闭眼伪报成已到达差分。
            lidmask[:]=0;tmp=Image.new('L',(W,H));d=ImageDraw.Draw(tmp)
            d.arc((cx-rx-18,cy-42,cx+rx+17,cy+23),5,175,fill=255,width=7)
            lidmask=np.array(tmp)/255.;v=np.empty_like(rgb);v[:]=[54,37,47]
        lname='eyelid'+suffix+'-'+state;save_asset(lname,v,lidmask,rect);lids[state]=lname+'.png'
    for state in ['open','half','closed']:
        whites['happy.'+state]=whites['happy'];lids['happy.'+state]=lids['happy']
    for special in ['teary','star','dizzy']:
        whites[special+'.open']=whites[special];lids[special+'.open']=lids[special]
        # 眨眼的半开口只截取特殊眼内部，闭眼仍用已验收的低位弧线。
        v=versions[special];halfMask=art['eyeWhite'+suffix+'-half'][:,:,3]/255.
        name='eyeWhite'+suffix+'-'+special+'-half';save_asset(name,v,halfMask,rect)
        whites[special+'.half']=name+'.png';lids[special+'.half']=lids['half']
        whites[special+'.closed']=whites['closed'];lids[special+'.closed']=lids['closed']
    add('eyeWhite'+suffix,art['eyeWhite'+suffix+'-open'][:,:,3]/255.,32,art['eyeWhite'+suffix+'-open'][:,:,:3],depth=.6,rect=rect,role='eyeWhite',side=side,variants=whites)
    irisMask=np.clip(ellipse(cx,cy,rx,ry)*100,0,1)
    irisKnown=irisMask*(rgb[:,:,2]-rgb[:,:,0]>24)
    irisRGB,_=extension(rgb,irisKnown,irisMask,.9)
    highlights=irisMask*(rgb[:,:,0]>215)*(rgb[:,:,1]>230)*(rgb[:,:,2]>230)
    irisRGB=cv2.inpaint(irisRGB.astype(np.uint8),(highlights*255).astype(np.uint8),4,cv2.INPAINT_TELEA)
    p=add('iris'+suffix,irisMask,34,irisRGB,depth=.61,rect=rect,role='pupil',side=side)
    p['mask']='eyeWhite'+suffix
    p=add('highlight'+suffix,blur(highlights,.4),35,rgb,depth=.61,rect=rect,role='highlight',side=side)
    p['mask']='eyeWhite'+suffix
    add('eyelid'+suffix,art['eyelid'+suffix+'-open'][:,:,3]/255.,36,art['eyelid'+suffix+'-open'][:,:,:3],depth=.62,rect=rect,role='eyelid',side=side,variants=lids)

# 原图眉线跨越刘海：只在发色遮罩内擦掉旧线，避免情绪眉出现双线。
browErase=Image.new('L',(W,H));bd=ImageDraw.Draw(browErase)
for pts in [[(303,735),(348,702),(393,682),(448,695)],[(591,690),(627,670),(672,679),(735,722)]]:
    curve=[]
    for t in np.linspace(0,1,100):
        curve.append(tuple((1-t)**3*np.array(pts[0])+3*(1-t)**2*t*np.array(pts[1])+3*(1-t)*t*t*np.array(pts[2])+t**3*np.array(pts[3])))
    bd.line(curve,fill=255,width=10)
browErase=np.array(browErase)*(front>.5)
hairRGB=cv2.inpaint(rgb.astype(np.uint8),browErase.astype(np.uint8),5,cv2.INPAINT_TELEA).astype(np.float32)
# 刘海和双侧层的隐藏边由同层邻近纹理补足，转头时不会露出原五官副本。
for name,mask,z,piv,chain,depth in [('sideHairLeft',sideL,50,(230,696),'sideLeft',.46),('sideHairRight',sideR,51,(800,694),'sideRight',.46),('frontHair',front,52,(515,454),'front',.48)]:
    # 仅向相邻发片内部做22px纹理搭接，不向脸/外轮廓膨胀。
    overlap=np.clip(1-ndimage.distance_transform_edt(mask<.5)/22,0,1)*hair
    support=np.maximum(grow(mask,1),overlap)
    support*=np.where(browErase>0, np.clip((hairRGB[:,:,2]-hairRGB[:,:,0]-2)/18,0,1),1)
    im,_=extension(hairRGB,np.maximum(mask,grow(mask,22)*hair),support,.6)
    p=add(name,blur(support,.45),z,im,depth=depth,physics=chain,pivot=piv)
    if name in ['sideHairLeft','sideHairRight']:p['weights']={'axis':'y','from':810,'to':1205,'power':1.7}
add('ahoge',ahoge,53,rgb,depth=.45,physics='ahoge',pivot=(514,441),weights={'axis':'y','from':441,'to':287,'power':1.5})
# 透发眉的曲线/颜色来自母版；低不透明度仅作用于额前刘海之上。
for side,points in [('Left',[(311,728),(350,702),(393,688),(435,691)]),('Right',[(596,689),(628,679),(669,682),(714,706)])]:
    names={}
    for state in ['neutral','happy','excited','surprised','sad','angry']:
        im=Image.new('RGBA',(W,H));d=ImageDraw.Draw(im)
        pts=[]
        for t in np.linspace(0,1,80):
            xy=(1-t)**3*np.array(points[0])+3*(1-t)**2*t*np.array(points[1])+3*(1-t)*t*t*np.array(points[2])+t**3*np.array(points[3])
            if state in ['happy','excited']:xy[1]-=5*np.sin(t*np.pi)
            if state=='surprised':xy[1]-=9
            if state=='sad':xy[1]+=(-7+14*t)*(1 if side=='Left' else -1)
            if state=='angry':xy[1]+=(9-18*t)*(1 if side=='Left' else -1)
            pts.append(tuple(xy))
        lineArray=np.zeros((H,W,4),np.uint8)
        cv2.polylines(lineArray,[np.round(np.array(pts)*16).astype(np.int32)],False,(32,45,85,255),3,cv2.LINE_AA,shift=4)
        im=Image.fromarray(lineArray)
        arr=np.array(im);name='brow'+side+'-'+state
        rect=[300,660,150,86] if side=='Left' else [586,648,144,92]
        browAlpha=arr[:,:,3]/255.*np.where(grow(front,2)>.25,.36,.82)
        save_asset(name,arr[:,:,:3],browAlpha,rect);names[state]=name+'.png'
    a=art['brow'+side+'-neutral']
    add('brow'+side,a[:,:,3]/255.,55,a[:,:,:3],rect=rect,depth=.59,role='brow',side=side.lower(),variants=names,opacity=1)
add('whaleClip',blur(whale,.5),57,rgb,depth=.5,pivot=(779,703))
add('tassel',blur(tassel,.5),58,rgb,depth=.41,physics='tassel',pivot=(828,664))
# 全部嘴型共用rect和柔边，缺失差分如实记录且以母版占位。
mouthRect=[465,897,120,88];mouthMask=np.clip(ellipse(524,940,58,40)*3,0,1)
mouthVariants={}
for key,sourcekey in [('N',None),('half','mouth_half'),('A','mouth_A'),('I','mouth_I'),('U','mouth_U'),('E','mouth_E'),('O','mouth_O'),('happy.N','mouth_happy'),('happy.A','mouth_happy'),('angry.N','mouth_angry'),('angry.A','mouth_angry'),('sad.N','mouth_sad'),('sad.A','mouth_sad'),('wavy.N','mouth_wavy'),('cat.N','mouth_cat'),('pout.N','mouth_pout'),('tongue.N','mouth_tongue'),('cry.N','mouth_cry'),('hmm.N','mouth_hmm')]:
    image=rgb if sourcekey is None else variant_image(sourcekey)
    factor={'mouth_A':.75,'mouth_O':.85,'mouth_U':1.3}.get(sourcekey,1)
    if sourcekey is not None:
        feature=((image[:,:,0]-image[:,:,1]>38)|(image[:,:,0]<180))*mouthMask
        feature=blur(grow(feature.astype(np.float32),3),.8)
        matrix=cv2.getRotationMatrix2D((522,934),0,factor)
        warped=cv2.warpAffine(image,matrix,(W,H),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REFLECT)
        weight=cv2.warpAffine(feature,matrix,(W,H),flags=cv2.INTER_LINEAR)
        image=warped*weight[:,:,None]+faceRGB*(1-weight[:,:,None])
    name='mouth-'+key.replace('.','-');save_asset(name,image,mouthMask,mouthRect);mouthVariants[key]=name+'.png'
add('mouth',mouthMask,38,rgb,depth=.64,pivot=(523,933),rect=mouthRect,role='mouth',variants=mouthVariants)

physics={}
for key,k,damp,maximum in [('back',65,15,3),('longLeft',48,13,4),('longRight',49,13,4),('sideLeft',55,14,3.5),('sideRight',57,14,3.5),('front',100,20,.35),('ahoge',40,9,8),('ribbonLeft',48,11,7),('ribbonRight',50,11,7),('tassel',27,8,9),('chest',85,16,2)]:
    physics[key]=dict(segments=3,stiffness=k,damping=damp,mass=1,maxAngle=maximum,drive={'yaw':.8,'pitch':.5,'roll':1.1,'bodyX':.04,'bodyY':.035})
pack=dict(version=1,name='whale-maid',title='小鲸鱼 · 女仆鲸鱼娘',credit='鲸鱼娘 · CC BY-NC-SA 4.0 · 上善无形 / ZipZipPipe',creditStyle=dict(right=430,bottom=4,fontSize=12,opacity=.6),canvas=dict(width=W,height=H,anchorX=519,anchorY=1536,charHeight=1260),render=dict(pixelRatio=1.5,maxFps=60,padding=80,rim=dict(enabled=True,color=[.27,.58,1],width=1,strength=.23)),groups=[dict(id='root',pivot=[519,1536]),dict(id='body',parent='root',pivot=[519,1536],bindings=dict(x=dict(param='bodyX'),y=dict(param='bodyY'),rotation=dict(param='bodyRoll'))),dict(id='head',parent='body',pivot=[520,1035],bindings=dict(rotation=dict(param='roll',gain=2.3)))],parts=parts,parameters=dict(blush=dict(min=0,max=1,value=.82)),deformers=dict(face=dict(type='head',pivot=[519,846],angle=[10,8],parallax=[190,130],compress=.055,curve=.065),hair=dict(type='bend',param='roll',angle=.65,axis='y'),breath=dict(type='breath',center=[520,1215],radius=[310,250],amount=[3.2,-4.4])),physics=physics,motion=dict(smoothing=10,breathPeriod=3.8,breathAmount=.75,floatPeriod=7.2,floatAmount=1.6,swayPeriod=8.4,swayAmount=.14,gazeGap=[3.2,6.8],gazeAmount=[.16,.08],talkRoll=.22),blink=dict(minGap=2.7,maxGap=5.2,duration=.19,doubleChance=.17,doubleDelay=.3,asymmetry=.014),eyes=dict(travel=[10,7],browTravel=4,highlightPulse=.04,highlightSpeed=2.0,halfThreshold=.7,closedThreshold=.23),mouth=dict(halfLevel=.022,openLevel=.07,hysteresis=.7,gain=6,minOpen=.75,transition=.055),emotions=dict(neutral=dict(pose={'blush':.82},effects=[]),happy=dict(pose={'blush':1,'roll':-.07},brow='happy',eyeVariant='happy',mouthVariant='happy',action=dict(duration=1.3,jump=7,cycles=2),effects=[dict(kind='star',x=836,y=610,size=43)]),excited=dict(pose={'blush':1,'roll':.09},brow='excited',mouthVariant='happy',action=dict(duration=1.7,jump=13,cycles=3),effects=[dict(kind='star',x=860,y=570,size=46,count=3)]),surprised=dict(pose={'brow':-.5,'blush':.5},brow='surprised',action=dict(duration=.55,jump=15,cycles=1),effects=[dict(kind='bubble',x=850,y=610,size=43)]),sad=dict(pose={'pitch':.2,'roll':-.1,'blush':.35},eyes=dict(left='half',right='half'),brow='sad',mouthVariant='sad',effects=[dict(kind='drop',x=778,y=900,size=28)]),angry=dict(pose={'brow':.25,'blush':.95},brow='angry',mouthVariant='angry',action=dict(duration=.7,shake=3,frequency=28),effects=[dict(kind='anger',x=803,y=641,size=42)])),behaviors=dict(enabled=True,look=dict(cooldown=8,duration=2.3,pose=dict(yaw=-.55,gazeX=-.72,roll=-.06),nodChance=.25,nodAmount=.16),gift=dict(cooldown=3,duration=2.6,emotion='happy',effects=[dict(kind='heart',x=812,y=610,size=40,count=3),dict(kind='star',x=224,y=730,size=33)]),worry=dict(threshold=.3,pose=dict(pitch=.12,brow=.2),brow='sad',effectGap=10,effects=[dict(kind='drop',x=775,y=895,size=26)]),think=dict(gap=[14,26],duration=3,pose=dict(roll=.2,gazeY=-.45,gazeX=.12)),gameOver=dict(duration=2,pose=dict(pitch=.15,gazeX=0,gazeY=0))),provenance=dict(masterSHA256=master_hash,missingVariants=sorted(set(missing)),recommendedDisplay=dict(charHeight=400,anchorX=1712,anchorY=1080,flip=False,credit=True)))
# 新表情采用同一母版局部差分；说话时非N口型仍回退到对应音素，不冻结整段讲话嘴型。
hideEyes={name:0 for name in ['irisLeft','irisRight','highlightLeft','highlightRight']}
pack['parameters'].update(browLeft=dict(min=-1,max=1,value=0),browRight=dict(min=-1,max=1,value=0),cheekPuff=dict(min=0,max=1,value=0))
pack['deformers']['cheeks']=dict(type='cheek',centers=[[354,923],[687,913]],radius=[88,50],amount=[12,3],param='cheekPuff')
for part in parts:
    if part['id'] in ['face','blushLeft','blushRight']:part['deformers'].append('cheeks')
pack['emotions'].update(
    shy=dict(pose=dict(blush=1,yaw=-.25,gazeX=.4,roll=-.14),brow='sad',mouthVariant='wavy',oscillations=dict(bodyRoll=dict(amplitude=.18,period=2.4)),effectInterval=1.4,effects=[dict(kind='blushLines',x=x,y=y,size=57,rise=0,duration=2,parent='head',opacity=.65) for x,y in [(354,919),(687,909)]]),
    smug=dict(pose=dict(blush=.8,pitch=-.16,roll=.13,brow=.3),eyes=dict(left='half',right='half'),brow='angry',mouthVariant='cat',effectInterval=2.0,effects=[dict(kind='star',x=803,y=650,size=31,rise=45,duration=1.3)]),
    confused=dict(pose=dict(blush=.6,roll=.38,browLeft=-1,browRight=.7,gazeX=-.1),brow='neutral',mouthVariant='hmm',effectInterval=1.7,effects=[dict(kind='question',x=815,y=475,size=70,rise=12,duration=2.2,parent='head')]),
    cry=dict(pose=dict(blush=.9,pitch=.13,roll=-.06),brow='sad',eyeVariant='teary',layerOpacity=hideEyes,mouthVariant='cry',oscillations=dict(bodyY=dict(amplitude=1.8,period=.43),roll=dict(amplitude=.045,period=.6)),effectInterval=.85,effects=[dict(kind='tear',x=x,y=y,size=22,rise=-95,duration=1.55,parent='head',depth=.62) for x,y in [(310,887),(738,878)]]),
    pout=dict(pose=dict(blush=1,cheekPuff=1,brow=.15),brow='angry',mouthVariant='pout',action=dict(duration=.7,jump=9,cycles=2),effectInterval=1.8,effects=[dict(kind='steam',x=807,y=628,size=58,rise=45,duration=1.5)]),
    starry=dict(pose=dict(blush=1,pitch=-.12,bodyY=-3),brow='excited',eyeVariant='star',layerOpacity=hideEyes,mouthVariant='happy',oscillations=dict(bodyRoll=dict(amplitude=.1,period=2.5)),effectInterval=1.1,effects=[dict(kind='star',x=825,y=610,size=38,rise=60,duration=1.5,count=3,spread=[125,80])]),
    dizzy=dict(pose=dict(blush=.75),brow='neutral',eyeVariant='dizzy',layerOpacity=hideEyes,mouthVariant='wavy',oscillations=dict(yaw=dict(amplitude=.15,period=2.1),pitch=dict(amplitude=.12,period=2.1,phase=1.5708),roll=dict(amplitude=.25,period=2.1)),effectInterval=1.9,effects=[dict(kind='orbit',x=520,y=355,size=125,rise=0,duration=2.5,parent='head')]),
    playful=dict(pose=dict(blush=1,roll=-.27,gazeX=.1),eyes=dict(left='closed',right='open'),eyeVariant=dict(left='happy'),brow='happy',mouthVariant='tongue',action=dict(duration=.9,jump=6,cycles=2),effectInterval=1.6,effects=[dict(kind='heart',x=817,y=657,size=37,rise=55,duration=1.8)])
)
for p in parts:
    p['mesh']=[14,16] if 'Hair' in p['id'] or p['id'] in ['body','backHair'] else [18,18] if p['id']=='face' else [6,6]
    if p.get('role') in ['mouth','brow']:p['mesh']=[4,4]
    if p.get('variants'):p['image']=p['variants'].get('open',p['variants'].get('neutral',p['variants'].get('N',p['image'])))
(OUT/'rig.json').write_text(json.dumps(pack,ensure_ascii=False,indent=2)+'\n')
# 可读归属置于包目录，源图生成记录仍由母版目录单独保存。
(OUT/'ATTRIBUTION.md').write_text('# 女仆鲸鱼娘 · 小鲸鱼\n\n角色采用 **CC BY-NC-SA 4.0**，仅限非商业直播。\n\n- 原型「溟月」：B站 @上善无形。\n- 女仆鲸鱼娘设计：B站 @ZipZipPipe。\n- 母版由 AI 图片模型基于用户提供的参考图生成；本包以原生 1024×1536 母版进行本地修复、分层、遮挡补全与网格绑定，没有伪造放大。\n- 本文件不代替原作者授权证明；二次分发需保留署名、非商业与相同方式共享条件。\n\n协议：https://creativecommons.org/licenses/by-nc-sa/4.0/\n')
# 中性重组是逐部件合成，用于观察真实分层结果，不把母版用作运行底板。
composite=Image.new('RGBA',(W,H))
for p in sorted(parts,key=lambda p:p['z']):
    a=art[p['id']].copy()
    if 'role' in p:
        if p['role'] in ['pupil','highlight']:
            m=art['eyeWhite'+p['side'].title()+'-open'][:,:,3]/255.
            a[:,:,3]=(a[:,:,3]*m).astype(np.uint8)
    opacity=p.get('opacity',1)*(.82 if p.get('opacityParam')=='blush' else 1)
    a[:,:,3]=(a[:,:,3]*opacity).astype(np.uint8)
    composite=Image.alpha_composite(composite,Image.fromarray(a))
composite.save(PROOF/'neutral-reassembled.png')
bg=Image.new('RGBA',(W,H),(22,42,70,255));Image.alpha_composite(bg,composite).convert('RGB').save(PROOF/'neutral-reassembled-blue.png')
Image.alpha_composite(bg,composite).crop((180,620,840,1040)).resize((1320,840)).save(PROOF/'face-reassembled-detail.png')
print('正式包部件',len(parts),'缺失差分',sorted(set(missing)))
