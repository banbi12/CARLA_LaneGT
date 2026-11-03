"""Observe broad repeated paint bars, independent of map polygons and image axes.

This module labels observed paint pixels only. Pedestrian-crossing GT continues
to come from the separately selected XODR geometry.
"""
import cv2
import numpy as np

def observed_stripes(paint, scale, policy):
    radius = max(policy['stripe_seed_radius_m'],policy['maximum_thin_width_m']/2+scale*.2)
    distance = cv2.distanceTransform(paint.astype(np.uint8), cv2.DIST_L2, 5)*scale
    seeds = (distance >= radius).astype(np.uint8)
    # Crosswalk rails can connect every stripe into a ladder-shaped component.
    # Isolate long cores by direction before measuring individual bars. Sample
    # all directions equally; the world/image heading is not an acceptance gate.
    opened=[]
    length=max(3,int(round(max(.7,policy['stripe_min_length_m']-2*radius)/scale)))
    size=length+4
    if size%2==0:size+=1
    for angle in range(0,180,5):
        direction=np.array([np.cos(np.deg2rad(angle)),np.sin(np.deg2rad(angle))])
        ends=np.rint(np.array([size//2,size//2])+np.array([-.5,.5])[:,None]*length*direction).astype(int)
        kernel=np.zeros((size,size),np.uint8);cv2.line(kernel,tuple(ends[0]),tuple(ends[1]),1,1)
        opened.append(cv2.morphologyEx(seeds,cv2.MORPH_OPEN,kernel))
    bars=[];bar_seeds=[]
    for direction_mask in opened:
      count, labels, stats, centers = cv2.connectedComponentsWithStats(direction_mask,8)
      for index in range(1,count):
        x,y,w,h,area = stats[index]
        if area < 4:
            continue
        yy,xx = np.where(labels[y:y+h,x:x+w] == index)
        points = np.c_[xx+x,yy+y].astype(np.float32)
        rect = cv2.minAreaRect(points); a,b = sorted(rect[1],reverse=True)
        major,minor = (a+1)*scale+2*radius, (b+1)*scale+2*radius
        corners = cv2.boxPoints(rect); edges = np.roll(corners,-1,axis=0)-corners
        axis = edges[np.argmax(np.linalg.norm(edges,axis=1))].astype(float)
        axis /= max(np.linalg.norm(axis),1e-12)
        fill = area/max(1.,(a+1)*(b+1))
        if not (policy['stripe_min_length_m'] <= major <= policy['stripe_max_length_m']
                and policy['stripe_min_width_m'] <= minor <= policy['stripe_max_width_m']
                and major/minor >= policy['stripe_min_aspect'] and fill >= policy['stripe_min_fill']):
            continue
        # Keep the best-aligned decomposition when several openings see one bar.
        duplicate=next((i for i,item in enumerate(bars) if np.linalg.norm((np.asarray(item['center'])-centers[index])*scale)<.25
                        and abs(axis@np.asarray(item['axis']))>.96),None)
        record=dict(seed_label=len(bars),center=centers[index].tolist(),axis=axis.tolist(),length_m=major,width_m=minor,fill=fill)
        seed=np.zeros(paint.shape,np.uint8);seed[y:y+h,x:x+w]=(labels[y:y+h,x:x+w]==index).astype(np.uint8)
        if duplicate is None:bars.append(record);bar_seeds.append(seed)
        elif major*minor>bars[duplicate]['length_m']*bars[duplicate]['width_m']:
            record['seed_label']=duplicate;bars[duplicate]=record;bar_seeds[duplicate]=seed
    adjacency = {i:set() for i in range(len(bars))}
    for i,a in enumerate(bars):
        axis = np.asarray(a['axis']); normal = np.array([-axis[1],axis[0]])
        for j in range(i+1,len(bars)):
            b = bars[j]; delta = (np.asarray(b['center'])-a['center'])*scale
            lateral,longitudinal = abs(delta@normal),abs(delta@axis)
            if (abs(axis@np.asarray(b['axis'])) >= policy['stripe_parallel_dot']
                and policy['stripe_min_gap_m'] <= lateral <= policy['stripe_max_gap_m']
                and longitudinal <= policy['stripe_longitudinal_offset_m']
                and abs(a['length_m']-b['length_m']) <= .3*max(a['length_m'],b['length_m'])):
                adjacency[i].add(j);adjacency[j].add(i)
    seen, groups = set(), []
    for i in adjacency:
        if i in seen:
            continue
        group,queue = [],[i];seen.add(i)
        while queue:
            j = queue.pop();group.append(j)
            for k in sorted(adjacency[j]-seen):seen.add(k);queue.append(k)
        if len(group) >= policy['stripe_min_count']:
            groups.append(sorted(group))
    mask = np.zeros(paint.shape,bool);role_mask=np.zeros(paint.shape,np.uint8);footprints=[];yy,xx = np.indices(paint.shape)
    for group in groups:
        # The observed repeated bars define the pedestrian-paint role area.
        # Include their tips/rails inside that area, so skinny leftovers cannot
        # become dividers. This hull is measured from pixels, never an XODR box.
        corners=[]
        for index in group:
            bar=bars[index];axis=np.asarray(bar['axis']);normal=np.array([-axis[1],axis[0]])
            for sign_a in [-1,1]:
                for sign_b in [-1,1]:
                    corners.append(np.asarray(bar['center'])+(axis*sign_a*bar['length_m']/2+normal*sign_b*bar['width_m']/2)/scale)
        hull=cv2.convexHull(np.asarray(corners,np.float32)).reshape(-1,2)
        cv2.fillPoly(role_mask,[np.rint(hull).astype(np.int32)],1);footprints.append(hull.tolist())
        for index in group:
            bar = bars[index]; seed = bar_seeds[index]
            expanded = cv2.distanceTransform(1-seed,cv2.DIST_L2,5)*scale <= radius+scale*.6
            axis = np.asarray(bar['axis']);normal = np.array([-axis[1],axis[0]])
            delta = np.stack([xx-bar['center'][0],yy-bar['center'][1]],-1)*scale
            rect = (np.abs(delta@axis) <= bar['length_m']/2) & (np.abs(delta@normal) <= bar['width_m']/2)
            mask |= paint & expanded & rect
    stripe_body_pixels=int(mask.sum())
    mask |= paint & (role_mask>0)
    audit = dict(method='observed_repeated_bars_and_local_pedestrian_role_area',map_geometry_used=False,
                 bars=bars,groups=groups,masked_paint_pixels=int(mask.sum()),whole_crosswalk_polygon_masked=False)
    audit.update(stripe_body_pixels=stripe_body_pixels,observed_role_extra_paint_pixels=int(mask.sum())-stripe_body_pixels,observed_footprints_uv=footprints)
    return mask,audit
