import sys; sys.path.insert(0, "/tmp/skills_dl/onetake/scripts")
from sfx_palette import *
import numpy as np
s = Score(dur=25.0, T60=1.2)
E = [(0.25,'draw'),(0.95,'word'),(1.3,'word'),(2.35,'whoosh'),(3.95,'pencil'),(4.32,'pencil'),(4.58,'pencil'),
     (6.25,'hop'),(6.85,'hop'),(6.95,'no'),(8.35,'land'),(8.95,'chips'),(9.6,'card'),(13.35,'click'),(13.45,'whoosh'),
     (15.45,'number'),(16.25,'bars'),(18.55,'hit'),(18.8,'hit'),(19.05,'hit'),(19.3,'hit'),(21.2,'pass'),(22.4,'mark')]
for t,k in E:
    if k=='draw':  s.place(glass(784,0.9,0.5), t, gain=0.14, send=0.5)
    if k=='word':  s.place(wood(220,0.08), t, gain=0.22, send=0.2)
    if k=='whoosh':s.place(air(0.55,220,2800,1.3,0.55), t-0.1, gain=0.45, send=0.45, pan=-0.2, pan_to=0.2)
    if k=='pencil':s.place(air(0.16,1800,5200,2.2,0.2), t, gain=0.30, send=0.15, pan=0.3)
    if k=='hop':   s.place(bubble(480,0.18), t, gain=0.20, send=0.3, pan=-0.4)
    if k=='no':    s.place(wobble(140,0.5), t, gain=0.22, send=0.3, pan=-0.3)
    if k=='land':  s.place(sub(58,0.6), t, gain=0.55, send=0.2); s.place(glass(659,0.8,0.7), t, gain=0.12, send=0.5)
    if k=='chips': [s.place(wood(260+i*60,0.07), t+i*0.08, gain=0.16, send=0.25, pan=0.2+i*0.1) for i in range(3)]
    if k=='card':  s.place(air(0.35,400,1800,1.1,0.4), t, gain=0.25, send=0.35, pan=0.4)
    if k=='click': s.place(wood(180,0.1), t, gain=0.3, send=0.2)
    if k=='number':s.place(sub(62,0.7), t, gain=0.5, send=0.25); s.place(glass(880,1.1,0.6), t, gain=0.12, send=0.55)
    if k=='bars':  [s.place(wood(300+i*40,0.08), t+0.1+i*0.12, gain=0.14, send=0.25) for i in range(4)]
    if k=='hit':   s.place(sub(70,0.25), t, gain=0.42, send=0.15); s.place(wood(200,0.06), t, gain=0.2, send=0.1)
    if k=='pass':  s.place(glass(988,1.2,0.7), t, gain=0.16, send=0.55); s.place(sub(55,0.5), t, gain=0.35, send=0.2)
    if k=='mark':  s.place(glass(523,1.6,0.5), t+0.2, gain=0.14, send=0.6); s.place(glass(784,1.6,0.5), t+0.45, gain=0.11, send=0.6)
s.write("sfx.wav")
print("ok")
