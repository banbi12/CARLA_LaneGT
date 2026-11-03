/* Shared bounds and metric-preserving view transform. */
(function(root){'use strict';
const DEFAULT=[-15,-30,15,30];
function bounds(value){const b=value??DEFAULT;if(!Array.isArray(b)||b.length!==4||b.some(v=>typeof v!=='number'||!Number.isFinite(v))||b[0]>=b[2]||b[1]>=b[3])throw Error('无效BEV范围');return b.slice();}
function ring(value){const [a,b,c,d]=bounds(value);return [[a,b],[c,b],[c,d],[a,d],[a,b]];}
function mapping(value){const [a,b,c,d]=bounds(value);return [Math.min(600/(c-a),1200/(d-b)),(a+c)/2,(b+d)/2];}
function screen(p,value){const [s,x,y]=mapping(value);return [330+(p[0]-x)*s,630-(p[1]-y)*s];}
function world(p,value){const [s,x,y]=mapping(value);return [(p[0]-330)/s+x,(630-p[1])/s+y];}
function inside(p,value,tol=0){const [a,b,c,d]=bounds(value);return p[0]>=a-tol&&p[0]<=c+tol&&p[1]>=b-tol&&p[1]<=d+tol;}
function edge(p,value){return ring(value).some(q=>Math.abs(p[0]-q[0])<1e-7||Math.abs(p[1]-q[1])<1e-7);}
const api={bounds,ring,screen,world,inside,edge};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.BEVView=api;
})(typeof window!=='undefined'?window:globalThis);
