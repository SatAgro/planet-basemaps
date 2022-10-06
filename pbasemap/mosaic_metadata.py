#!/usr/bin/python
# -*- coding: utf-8 -*-

__copyright__ = """

    Copyright 2019 Samapriya Roy
    Copyright 2022 SatAgro, Krzysztof Stopa
    
    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

"""
__license__ = "Apache 2.0"

import os
from datetime import datetime

import pandas as pd
import geopandas as gpd
import requests
import sys
import pyproj
from functools import partial
from shapely.geometry import shape
from shapely.geometry import Polygon
from shapely.ops import transform
from shapely.geometry import box


PL_API_KEY = os.getenv('PL_API_KEY', '')


class DateRange:
    """
    Helper class for manage date ranges
    """

    def __init__(self, dt1, dt2):
        self._dt1 = dt1
        self._dt2 = dt2

    def __contains__(self, dt):
        return self._dt1 <= dt <= self._dt2


def _handle_page(response, geom_main_bound, start, end):
    quads = gpd.GeoDataFrame()
    time_range = DateRange(start, end)
    for mosaic in response['mosaics']:
        bd = mosaic['bbox']
        mosgeom = shape(Polygon(box(bd[0], bd[1], bd[2], bd[3]).exterior.coords))
        gboundlist = geom_main_bound.split(',')
        boundgeom = shape(
            Polygon(box(float(gboundlist[0]), float(gboundlist[1]), float(gboundlist[2]), float(gboundlist[3]))))
        proj = partial(pyproj.transform, pyproj.Proj(init='epsg:4326'), pyproj.Proj(init='epsg:3857'))
        boundgeom = transform(proj, boundgeom)
        mosgeom = transform(proj, mosgeom)
        first_acquired = datetime.strptime(mosaic['first_acquired'].split('T')[0], '%Y-%m-%d').date()
        last_acquired = datetime.strptime(mosaic['last_acquired'].split('T')[0], '%Y-%m-%d').date()
        mosaic_in_range = first_acquired in time_range and last_acquired in time_range
        if boundgeom.intersection(mosgeom).is_empty:
            print('Error: empty bounding box!')
        elif mosaic_in_range:
            mosaic_id = mosaic['id']
            r = requests.get('https://api.planet.com/basemaps/v1/mosaics/' + str(mosaic_id) + '/quads?bbox=' + str(
                gboundlist[0]) + '%2C' + gboundlist[1] + '%2C' + gboundlist[2] + '%2C' + gboundlist[3],
                             auth=(PL_API_KEY, ''))
            resp = r.json()
            for quad in resp['items']:
                quad_df = gpd.GeoDataFrame({
                    'mosaic_id': [str(mosaic['id'])],
                    'mosaic_name': [str(mosaic['name'])],
                    'quad_id': [quad['id']],
                    'geometry': box(quad['bbox'][0], quad['bbox'][1], quad['bbox'][2], quad['bbox'][3]),
                    'first_acquired': first_acquired.strftime('%Y-%m-%d'),
                    'last_acquired': last_acquired.strftime('%Y-%m-%d'),
                    'resolution': str(mosaic['grid']['resolution']),
                    'percent_covered': quad['percent_covered'],
                    'link_self': quad['_links']['_self'],
                    'link_thumbnail': quad['_links']['thumbnail'],
                    'link_item': quad['_links']['download'],
                    'link_download': quad['_links']['download'],
                }, crs="EPSG:4326", index=[0, 2])
                quads = pd.concat([quads, quad_df])
                quads.reset_index()
    return quads


def get_file_mosaic_quads_metadata(filepath, start_date, end_date, api_key=PL_API_KEY, intersect_exact=True):
    quads = gpd.GeoDataFrame()
    try:
        aoi_data = gpd.read_file(filepath)
        for aoi in aoi_data.itertuples():
            aoi_mosaics = get_aoi_mosaic_quads_metadata(aoi.geometry, start_date, end_date, api_key)
            quads = pd.concat([quads, aoi_mosaics])
            quads.reset_index()
        if intersect_exact:
            quads = aoi_data.overlay(quads)
    except ValueError as e:
        print(f'Could not parse file {filepath}. {e}')
    except Exception as e:
        print(f'Could not parse file {filepath}. {e}')
    finally:
        return quads


def get_aoi_mosaic_quads_metadata(aoi_geom, start, end, api_key=PL_API_KEY):
    """
    Get area of interest metadata.
    :param aoi_geom: Shapely shape
    :param start: Start date.
    :param end: End date.
    :param api_key: Planet API key.
    :return: Pandas DataFrame with found mosaic quads metadata.
    """
    quads = gpd.GeoDataFrame()
    gmainbound = (','.join(str(v) for v in list(aoi_geom.bounds)))
    print('rbox:' + str(gmainbound)+'\n')
    r = requests.get('https://api.planet.com/basemaps/v1/mosaics', auth=(api_key, ''))
    response = r.json()
    try:
        if response['mosaics'][0]['quad_download'] == True:
            resp_mosaics = _handle_page(response, gmainbound, start, end)
            quads = pd.concat([quads, resp_mosaics])
            quads.reset_index()
    except KeyError as e:
        print('No Download permission for: '+str(response['mosaics'][0]['name']) + 'Error: ' + str(e))
    try:
        while response['_links'].get('_next') is not None:
            page_url = response['_links'].get('_next')
            r = requests.get(page_url)
            response = r.json()
            try:
                if response['mosaics'][0]['quad_download'] == True:
                    resp_mosaics = _handle_page(response, gmainbound, start, end)
                    quads = pd.concat([quads, resp_mosaics])
                    quads.reset_index()
            except KeyError:
                print('No Download permission for: '+str(response['mosaics'][0]['name']))
            except Exception as e:
                print('Error downloading    thumbnail   for: ' + str(e))
    except Exception as e:
        print(e)
    except (KeyboardInterrupt, SystemExit) as e:
        print('Program escaped by User')
        sys.exit()
    finally:
        return quads.drop_duplicates()
