#!/usr/bin/env python3
"""Minimal OpenDRIVE road/lane successor topology for XODR-only stitching.

This parser reads only link/junction metadata; it does not reinterpret roadMark
geometry. It is intentionally independent of the geometric stitch heuristics.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class RoadLink:
    target_type: str
    target_id: int
    contact: str | None


@dataclass(frozen=True)
class RoadInfo:
    length: float
    predecessor: RoadLink | None
    successor: RoadLink | None


@dataclass(frozen=True)
class JunctionConnection:
    incoming: int
    connecting: int
    contact: str | None
    lane_links: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Endpoint:
    road_id: int
    lane_id: int
    contact: str  # start | end


class XodrTopology:
    def __init__(self, roads, lane_links, junctions):
        self.roads = roads
        self.lane_links = lane_links
        self.junctions = junctions

    @classmethod
    def from_file(cls, path):
        root = ET.parse(Path(path)).getroot()
        roads = {}
        lane_links = {}
        junctions = {}
        for road in root.findall('road'):
            rid = int(road.get('id'))
            link = road.find('link')
            pred = succ = None
            if link is not None:
                pred = _road_link(link.find('predecessor'))
                succ = _road_link(link.find('successor'))
            roads[rid] = RoadInfo(float(road.get('length', 0)), pred, succ)
            for lane in road.findall('lanes/laneSection/*/lane'):
                lid = int(lane.get('id'))
                lk = lane.find('link')
                if lk is None:
                    continue
                for tag in ('predecessor', 'successor'):
                    el = lk.find(tag)
                    if el is not None and el.get('id') is not None:
                        lane_links[(rid, lid, tag)] = int(el.get('id'))
        for junction in root.findall('junction'):
            jid = int(junction.get('id'))
            connections = []
            for c in junction.findall('connection'):
                connections.append(JunctionConnection(
                    incoming=int(c.get('incomingRoad')),
                    connecting=int(c.get('connectingRoad')),
                    contact=c.get('contactPoint'),
                    lane_links=tuple(
                        (int(x.get('from')), int(x.get('to')))
                        for x in c.findall('laneLink')
                    ),
                ))
            junctions[jid] = connections
        return cls(roads, lane_links, junctions)

    def describe(self):
        return {
            'roads': len(self.roads),
            'road_links': sum(
                (1 if r.predecessor else 0) + (1 if r.successor else 0)
                for r in self.roads.values()
            ),
            'lane_links': len(self.lane_links),
            'junctions': len(self.junctions),
            'junction_connections': sum(len(v) for v in self.junctions.values()),
            'junction_lane_links': sum(len(c.lane_links) for v in self.junctions.values() for c in v),
        }

    def targets(self, ep: Endpoint):
        road = self.roads.get(ep.road_id)
        if road is None or ep.contact not in ('start', 'end'):
            return []
        link = road.predecessor if ep.contact == 'start' else road.successor
        if link is None:
            return []
        direction = 'predecessor' if ep.contact == 'start' else 'successor'
        lane_map = self.lane_links.get((ep.road_id, ep.lane_id, direction), ep.lane_id)
        out = []
        if link.target_type == 'road':
            target_contact = link.contact if link.contact in ('start', 'end') else (
                'start' if ep.contact == 'end' else 'end'
            )
            out.append((Endpoint(link.target_id, lane_map, target_contact), 'road_link'))
        elif link.target_type == 'junction':
            for connection in self.junctions.get(link.target_id, []):
                if ep.contact == 'end' and connection.incoming == ep.road_id:
                    target_lanes = [to for frm, to in connection.lane_links if frm == ep.lane_id]
                    if not target_lanes and not connection.lane_links:
                        target_lanes = [ep.lane_id]
                    target_contact = connection.contact if connection.contact in ('start', 'end') else 'start'
                    for lane in target_lanes:
                        out.append((Endpoint(connection.connecting, lane, target_contact),
                                    'junction_connection'))
                elif ep.contact == 'start' and connection.connecting == ep.road_id:
                    target_lanes = [frm for frm, to in connection.lane_links if to == ep.lane_id]
                    if not target_lanes and not connection.lane_links:
                        target_lanes = [ep.lane_id]
                    target_contact = 'end' if connection.contact == 'start' else 'start'
                    for lane in target_lanes:
                        out.append((Endpoint(connection.incoming, lane, target_contact),
                                    'junction_reverse'))
        return out

    def relation(self, a: Endpoint, b: Endpoint):
        """Return a topology descriptor only when OpenDRIVE links the endpoints."""
        for target, kind in self.targets(a):
            if target == b:
                return {'kind': kind, 'from': _ep(a), 'to': _ep(b)}
        for target, kind in self.targets(b):
            if target == a:
                return {'kind': kind + '_reverse', 'from': _ep(b), 'to': _ep(a)}
        return None


def _road_link(element):
    if element is None:
        return None
    if element.get('elementType') not in ('road', 'junction') or element.get('elementId') is None:
        return None
    return RoadLink(
        target_type=element.get('elementType'),
        target_id=int(element.get('elementId')),
        contact=element.get('contactPoint'),
    )


def _ep(ep):
    return {'road_id': ep.road_id, 'lane_id': ep.lane_id, 'contact': ep.contact}
