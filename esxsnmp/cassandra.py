#!/usr/bin/env python
# encoding: utf-8
"""
Cassandra DB interface calls and data encapsulation objects.
"""
# Standard
import calendar
import datetime
import json
import logging
import os
import pprint
import sys
import time
from collections import OrderedDict

from esxsnmp.util import get_logger

# Third party
from pycassa import PycassaLogger
from pycassa.pool import ConnectionPool, AllServersUnavailable
from pycassa.columnfamily import ColumnFamily, NotFoundException
from pycassa.system_manager import *

from thrift.transport.TTransport import TTransportException

SEEK_BACK_THRESHOLD = 2592000 # 30 days

class CassandraException(Exception):
    """Common base"""
    pass

class ConnectionException(CassandraException):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)
        
class CASSANDRA_DB(object):
    
    keyspace = 'esxsnmp'
    raw_cf = 'raw_data'
    rate_cf = 'base_rates'
    agg_cf = 'rate_aggregations'
    stat_cf = 'stat_aggregations'
    
    _queue_size = 200
    
    def __init__(self, config, qname=None, clear_on_test=False):
        """
        Class contains all the relevent cassandra logic.  
        """
        
        # Configure logging
        if qname:
            self.log = get_logger("espersistd.%s.cass_db" % qname)
        else:
            self.log = logging.getLogger('cassandra_db')
            self.log.setLevel(logging.DEBUG)
            format = logging.Formatter('%(name)s [%(levelname)s] %(message)s')
            handle = logging.StreamHandler()
            handle.setFormatter(format)
            self.log.addHandler(handle)
        
        # Add pycassa logging to existing logger - thanks for not using the 
        # standard logging numeric macros pycassa!  :(
        levels = {10: 'debug', 20: 'info', 30: 'warn', 40: 'error', 50: 'critial'}
        plog = PycassaLogger()
        plog.set_logger_name('%s.pycassa' % self.log.name)
        # clog.set_logger_level(levels[self.log.getEffectiveLevel()])
        # Debug is way to noisy, just set to info....
        plog.set_logger_level('info')

        # Connect with SystemManager, do a schema check and setup if need be
        try:
            sysman = SystemManager(config.cassandra_servers[0])                              
        except TTransportException, e:
            raise ConnectionException("System Manager can't connect to Cassandra "
                "at %s - %s" % (config.cassandra_servers[0], e))
        
        # Blow everything away if we're testing
        if clear_on_test and os.environ.get("ESXSNMP_TESTING", False):
            self.log.info('Dropping keyspace %s' % self.keyspace)
            if self.keyspace in sysman.list_keyspaces():
                sysman.drop_keyspace(self.keyspace)
                time.sleep(3)
        # Create keyspace
        if not self.keyspace in sysman.list_keyspaces():
            self.log.info('Creating keyspace %s' % self.keyspace)
            sysman.create_keyspace(self.keyspace, SIMPLE_STRATEGY, 
                {'replication_factor': '1'})
        # Create column families
        self.log.info('Checking/creating column families')
        # Raw Data CF
        if not sysman.get_keyspace_column_families(self.keyspace).has_key(self.raw_cf):
            sysman.create_column_family(self.keyspace, self.raw_cf, super=False, 
                    comparator_type=LONG_TYPE, 
                    default_validation_class=LONG_TYPE,
                    key_validation_class=UTF8_TYPE)
            self.log.info('Created CF: %s' % self.raw_cf)
        # Base Rate CF
        if not sysman.get_keyspace_column_families(self.keyspace).has_key(self.rate_cf):
            sysman.create_column_family(self.keyspace, self.rate_cf, super=True, 
                    comparator_type=LONG_TYPE, 
                    default_validation_class=COUNTER_COLUMN_TYPE,
                    key_validation_class=UTF8_TYPE)
            self.log.info('Created CF: %s' % self.rate_cf)
        # Rate aggregation CF
        if not sysman.get_keyspace_column_families(self.keyspace).has_key(self.agg_cf):
            sysman.create_column_family(self.keyspace, self.agg_cf, super=True, 
                    comparator_type=LONG_TYPE, 
                    default_validation_class=COUNTER_COLUMN_TYPE,
                    key_validation_class=UTF8_TYPE)
            self.log.info('Created CF: %s' % self.agg_cf)
        # Stat aggregation CF
        if not sysman.get_keyspace_column_families(self.keyspace).has_key(self.stat_cf):
            sysman.create_column_family(self.keyspace, self.stat_cf, super=True, 
                    comparator_type=LONG_TYPE, 
                    default_validation_class=LONG_TYPE,
                    key_validation_class=UTF8_TYPE)
            self.log.info('Created CF: %s' % self.stat_cf)
                    
        sysman.close()
        
        self.log.info('Schema check done')
        
        if clear_on_test and os.environ.get("ESXSNMP_TESTING", False):
            if len(config.cassandra_servers) > 1:
                self.log.info("Waiting for schema to propogate...")
                print 'Waiting for schema to propogate...'
                time.sleep(10)
                self.log.info("Done")
                print 'Done'
        
        # Now, set up the ConnectionPool
        
        _creds = {}
        if config.cassandra_user and config.cassandra_pass:
            _creds['username'] = config.cassandra_user
            _creds['password'] = config.cassandra_pass
            self.log.debug('Connecting with username: %s' % (config.cassandra_user,))
        
        try:
            self.log.debug('Opening ConnectionPool')
            self.pool = ConnectionPool(self.keyspace, 
                server_list=config.cassandra_servers, 
                pool_size=10,
                max_overflow=5,
                max_retries=10,
                timeout=30,
                credentials=_creds)
        except AllServersUnavailable, e:
            raise ConnectionException("Couldn't connect to any Cassandra "
                    "at %s - %s" % (config.cassandra_servers, e))
                    
        self.log.info('Connected to %s' % config.cassandra_servers)
        
        # Column family connections
        self.raw_data = ColumnFamily(self.pool, self.raw_cf).batch(self._queue_size)
        self.rates    = ColumnFamily(self.pool, self.rate_cf).batch(self._queue_size)
        self.aggs     = ColumnFamily(self.pool, self.agg_cf).batch(self._queue_size)
        self.stat_agg = ColumnFamily(self.pool, self.stat_cf).batch(self._queue_size)
        
        # Timing
        self.profiling = False
        if config.db_profile_on_testing and os.environ.get("ESXSNMP_TESTING", False):
            self.profiling = True
        self.stats = DatabaseMetrics(profiling=self.profiling)
        
        # Class members
        self.raw_opts = {}
        self.raw_expire = config.cassandra_raw_expire
        if self.raw_expire:
            self.raw_opts['ttl'] = int(self.raw_expire)
        self.metadata_cache = {}
        
        # Initialize metadata cache in cases of a restart.
        # Disabled for now.
        # self._initialize_metadata()
        
    def flush(self):
        self.log.debug('Flush called')
        self.raw_data.send()
        self.rates.send()
        self.aggs.send()
        self.stat_agg.send()
        
    def close(self):
        self.log.debug('Close/dispose called')
        self.pool.dispose()
        
    def set_raw_data(self, raw_data):
        t = time.time()
        self.raw_data.insert(raw_data.get_key(), 
            {raw_data.ts_to_unixtime(): raw_data.val}, **self.raw_opts)
        
        if self.profiling: self.stats.raw_insert(time.time() - t)
        
    def set_metadata(self, meta_d):
        # Do this in memory for now
        self.metadata_cache[meta_d.get_meta_key()] = meta_d.get_document()
        
    def get_metadata(self, raw_data):
        t = time.time()

        meta_d = None
        
        if not self.metadata_cache.has_key(raw_data.get_meta_key()):
            # Didn't find a value in the metadata cache.  First look
            # back through the raw data for SEEK_BACK_THRESHOLD seconds
            # to see if we can find the last processed value.
            ts_max = raw_data.ts_to_unixtime() - 1 # -1 to look at older vals
            ts_min = ts_max - SEEK_BACK_THRESHOLD
            ret = self.raw_data._column_family.multiget(
                    self._get_row_keys(raw_data.device,raw_data.path,raw_data.oid,
                            raw_data.freq,ts_min,ts_max),
                    # Note: ts_max and ts_min appear to be reversed here - 
                    # that's because this is a reversed range query.
                    column_start=ts_max, column_finish=ts_min,
                    column_count=1, column_reversed=True)
                    
            if self.profiling: self.stats.meta_fetch((time.time() - t))
                    
            if ret:
                # A previous value was found in the raw data, so we can
                # seed/return that.
                key = ret.keys()[0]
                ts = ret[key].keys()[0]
                val = ret[key][ts]
                meta_d = Metadata(last_update=ts, last_val=val, min_ts=ts, 
                    freq=raw_data.freq, **raw_data.get_path())
                self.log.debug('Metadata lookup from raw_data for: %s' %\
                        (meta_d.get_meta_key()))
            else:
                # No previous value was found (or at least not one in the defined
                # time range) so seed/return the current value.
                meta_d = Metadata(last_update=raw_data.ts, last_val=raw_data.val,
                    min_ts=raw_data.ts, freq=raw_data.freq, **raw_data.get_path())
                self.log.debug('Initializing metadata for: %s' %\
                        (meta_d.get_meta_key()))
            self.set_metadata(meta_d)
        else:
            meta_d = Metadata(**self.metadata_cache[raw_data.get_meta_key()])
        
        return meta_d
        
    def update_metadata(self, metadata):
        """
        """
        t = time.time()
        for i in ['last_val', 'min_ts', 'last_update']:
            self.metadata_cache[metadata.get_meta_key()][i] = getattr(metadata, i)
        #self.stats.meta_update((time.time() - t))
        
    def _initialize_metadata(self):
        """
        Rebuild in-memory metadata from raw data in the case of a restart.
        
        Currently not used, leaving for reference.
        """
        keys = {}

        # Build a dict of the years for a given device/path/oid/frequency. Will need
        # that do figure out which year/row to query for a given set.
        for k in self.raw_data._column_family.get_range(column_count=0,filter_empty=False):
            device,path,oid,freq,year = k[0].split(RawData._key_delimiter)
            base_key = RawData._key_delimiter.join([device,path,oid,freq])
            if not keys.has_key(base_key):
                keys[base_key] = []
            keys[base_key].append(int(year))
            pass
        
        # Generate a row key for the latest year for a given device/path/oid/freq
        for k,v in keys.items():
            year = 0
            for y in keys[k]:
                if y > year: 
                    year = y
            row_key = '%s%s%s' % (k, RawData._key_delimiter, year)
            device,path,oid,freq = k.split(RawData._key_delimiter)

            ret = self.raw_data._column_family.get(row_key, column_count=1, 
                            column_reversed=True)
            last_ts = ret.keys()[-1]
            val = ret[last_ts]
            # Initialize the same way as get_metadata() does.
            meta_d = Metadata(last_update=last_ts, last_val=val, min_ts=last_ts, 
                freq=freq, device=device, path=path, oid=oid)
            self.set_metadata(meta_d)

        pass
        
    def update_rate_bin(self, ratebin):
        t = time.time()
        
        self.rates.insert(ratebin.get_key(),
            {ratebin.ts_to_unixtime(): {'val': ratebin.val, 'is_valid': ratebin.is_valid}})
        
        if self.profiling: self.stats.baserate_update((time.time() - t))
        
    def update_rate_aggregation(self, raw_data, agg_ts, freq):
        
        t = time.time()
        
        agg = AggregationBin(
            ts=agg_ts, freq=freq, val=raw_data.val, base_freq=raw_data.freq, count=1,
            min=raw_data.val, max=raw_data.val, **raw_data.get_path()
        )
        
        self.aggs.insert(agg.get_key(), 
            {agg.ts_to_unixtime(): {'val': agg.val, str(agg.base_freq): 1}})
        
        if self.profiling: self.stats.aggregation_update((time.time() - t))
        
    def update_stat_aggregation(self, raw_data, agg_ts, freq):
        
        updated = False
        
        agg = AggregationBin(
            ts=agg_ts, freq=freq, val=raw_data.val, base_freq=raw_data.freq, count=1,
            min=raw_data.val, max=raw_data.val, **raw_data.get_path()
        )
        
        t = time.time()
        
        ret = None
        
        try:
            ret = self.stat_agg._column_family.get(agg.get_key(), 
                        super_column=agg.ts_to_unixtime())
        except NotFoundException:
            pass
        
        if self.profiling: self.stats.stat_fetch((time.time() - t))
        
        t = time.time()
        
        if not ret:
            self.stat_agg.insert(agg.get_key(),
                {agg.ts_to_unixtime(): {'min': agg.val, 'max': agg.val}})
            updated = True
        elif agg.val > ret['max']:
            self.stat_agg.insert(agg.get_key(),
                {agg.ts_to_unixtime(): {'max': agg.val}})
            updated = True
        elif agg.val < ret['min']:
            self.stat_agg.insert(agg.get_key(),
                {agg.ts_to_unixtime(): {'min': agg.val}})
            updated = True
        else:
            pass
        
        if self.profiling: self.stats.stat_update((time.time() - t))
        
        return updated
        
    def _get_row_keys(self, device, path, oid, freq, ts_min, ts_max):
        full_path = '%s:%s:%s:%s' % (device,path,oid,freq)
        
        year_start = datetime.datetime.utcfromtimestamp(ts_min).year
        year_finish = datetime.datetime.utcfromtimestamp(ts_max).year
        
        key_range = []
        
        if year_start != year_finish:
            for i in range(year_start, year_finish+1):
                key_range.append('%s:%s' % (full_path,i))
        else:
            key_range.append('%s:%s' % (full_path, year_start))
            
        return key_range
        
    def query_baserate_timerange(self, device=None, path=None, oid=None, 
                freq=None, ts_min=None, ts_max=None, cf='average', as_json=False):
        
        ret = self.rates._column_family.multiget(
                self._get_row_keys(device,path,oid,freq,ts_min,ts_max), 
                column_start=ts_min, column_finish=ts_max)
                
        if cf not in ['average', 'delta']:
            # XXX(mmg): log this as an error
            print cf, 'not a valid option, defaulting to average'
            cf = 'average'
                
        value_divisors = { 'average': int(freq), 'delta': 1}
        
        # Just return the results and format elsewhere.
        results = []
        
        for k,v in ret.items():
            for kk,vv in v.items():
                results.append({'ts': kk, 'val': float(vv['val']) / value_divisors[cf], 
                                        'is_valid': vv['is_valid']})
            
        if as_json: # format results for query interface
            # Get the frequency from the metatdata if the result set is empty
            if not results:
                pass
            return FormattedOutput.base_rate(ts_min, ts_max, results, freq)
        else:
            return results
            
    def query_aggregation_timerange(self, device=None, path=None, oid=None, 
                ts_min=None, ts_max=None, freq=None, cf=None, as_json=False):
                
        if cf not in ['average', 'min', 'max']:
            # XXX(mmg): log this as an error
            print cf, 'not a valid option, defaulting to average'
            cf = 'average'
        
        if cf == 'average':
            ret = self.aggs._column_family.multiget(
                    self._get_row_keys(device,path,oid,freq,ts_min,ts_max), 
                    column_start=ts_min, column_finish=ts_max)

            # Just return the results and format elsewhere.
            results = []
        
            for k,v in ret.items():
                for kk,vv in v.items():
                    ts = kk
                    val = None
                    base_freq = None
                    count = None
                    for kkk in vv.keys():
                        if kkk == 'val':
                            val = vv[kkk]
                        else:
                            base_freq = kkk
                            count = vv[kkk]
                results.append(
                    {'ts': ts, 'val': val, 'base_freq': int(base_freq), 'count': count}
                )
        elif cf == 'min' or cf == 'max':
            ret = self.stat_agg._column_family.multiget(
                    self._get_row_keys(device,path,oid,freq,ts_min,ts_max), 
                    column_start=ts_min, column_finish=ts_max)
            
            results = []
            
            for k,v in ret.items():
                for kk,vv in v.items():
                    ts = kk
                            
                if cf == 'min':
                    results.append({'ts': ts, 'min': vv['min']})
                else:
                    results.append({'ts': ts, 'max': vv['max']})
        
        if as_json: # format results for query interface
            return FormattedOutput.aggregate_rate(ts_min, ts_max, results, freq,
                    cf.replace('average', 'avg'))
        else:
            return results
            
    def query_raw_data(self, device=None, path=None, oid=None, freq=None,
                ts_min=None, ts_max=None, as_json=False):
                
        ret = self.raw_data._column_family.multiget(
                self._get_row_keys(device,path,oid,freq,ts_min,ts_max), 
                column_start=ts_min, column_finish=ts_max)

        # Just return the results and format elsewhere.
        results = []

        for k,v in ret.items():
            for kk,vv in v.items():
                results.append({'ts': kk, 'val': vv})
        
        if as_json: # format results for query interface
            return FormattedOutput.raw_data(ts_min, ts_max, results, freq)
        else:
            return results
            
    def __del__(self):
        pass

class FormattedOutput(object):
    
    @staticmethod
    def _from_datetime(d):
        if type(d) != type(datetime.datetime.now()):
            return d
        else:
            return calendar.timegm(d.utctimetuple())
    
    @staticmethod
    def base_rate(ts_min, ts_max, results, freq=None):
        fmt = [
            ('agg', freq if freq else results[0]['freq']),
            ('end_time', ts_max),
            ('data', []),
            ('cf', 'average'),
            ('begin_time', ts_min)
        ]
        
        fmt = OrderedDict(fmt)
        
        for r in results:
            fmt['data'].append(
                [
                    FormattedOutput._from_datetime(r['ts']), 
                    None if r['is_valid'] == 0 else float(r['val'])
                ]
            )
        
        return json.dumps(fmt)
        
    @staticmethod
    def aggregate_rate(ts_min, ts_max, results, freq, cf):
        fmt = [
            ('agg', freq),
            ('end_time', ts_max),
            ('data', []),
            ('cf', cf),
            ('begin_time', ts_min)
        ]
    
        fmt = OrderedDict(fmt)
        
        for r in results:
            ro = AggregationBin(**r)
            fmt['data'].append(
                [
                    ro.ts_to_unixtime(),
                    getattr(ro, cf)
                ]
            )
            
        return json.dumps(fmt)
        
    @staticmethod
    def raw_data(ts_min, ts_max, results, freq=None):
        fmt = [
            ('agg', freq if freq else results[0]['freq']),
            ('end_time', ts_max),
            ('data', []),
            ('cf', 'raw'),
            ('begin_time', ts_min)
        ]
        
        fmt = OrderedDict(fmt)
        
        for r in results:
            fmt['data'].append(
                [
                    FormattedOutput._from_datetime(r['ts']), 
                    float(r['val'])
                ]
            )
        
        return json.dumps(fmt)

# Stats/timing code for connection class

class DatabaseMetrics(object):
    
    _individual_metrics = [
        'raw_insert', 
        'baserate_update',
        'aggregation_update',
        'meta_fetch',
        'stat_fetch', 
        'stat_update',
    ]
    _all_metrics = _individual_metrics + ['total', 'all']
    
    def __init__(self, profiling=False):
        
        self.profiling = profiling
        
        if not self.profiling:
            return
        
        for im in self._individual_metrics:
            setattr(self, '%s_time' % im, 0)
            setattr(self, '%s_count' % im, 0)
        
    def _increment(self, m, t):
        setattr(self, '%s_time' % m, getattr(self, '%s_time' % m) + t)
        setattr(self, '%s_count' % m, getattr(self, '%s_count' % m) + 1)

    def raw_insert(self, t):
        self._increment('raw_insert', t)

    def baserate_update(self, t):
        self._increment('baserate_update', t)

    def aggregation_update(self, t):
        self._increment('aggregation_update', t)
        
    def meta_fetch(self, t):
        self._increment('meta_fetch', t)
        
    def stat_fetch(self, t):
        self._increment('stat_fetch', t)

    def stat_update(self, t):
        self._increment('stat_update', t)
        
    def report(self, metric='all'):
        
        if not self.profiling:
            print 'Not profiling'
            return
        
        if metric not in self._all_metrics:
            print 'bad metric' # XXX(mmg): log this
            return
            
        s = ''
        time = count = 0
            
        if metric in self._individual_metrics:
            datatype, action = metric.split('_')
            action = action.title()
            time = getattr(self, '%s_time' % metric)
            count = getattr(self, '%s_count' % metric)
            if time: # stop /0 errors
                s = '%s %s %s data in %.3f (%.3f per sec)' \
                    % (action, count, datatype, time, (count/time))
                if metric.find('total') > -1:
                    s += ' (informational - not in total)'
        elif metric == 'total':
            for k,v in self.__dict__.items():
                if k.find('total') > -1:
                    # don't double count the agg total numbers
                    continue
                if k.endswith('_count'):
                    count += v
                elif k.endswith('_time'):
                    time += v
                else:
                    pass
            if time:
                s = 'Total: %s db transactions in %.3f (%.3f per sec)' \
                    % (count, time, (count/time))
        elif metric == 'all':
            for m in self._all_metrics:
                if m == 'all':
                    continue
                else:
                    self.report(m)
                    
        if len(s): print s # XXX(mmg): log this


# Data encapsulation objects
        
class DataContainerBase(object):
    
    _doc_properties = []
    _key_delimiter = ':'
    
    def __init__(self, device, oidset, oid, path, _id):
        self.device = device
        self.oidset = oidset
        self.oid = oid
        self.path = path
        self._id = _id
        
    def _handle_date(self,d):
        # don't reconvert if we are instantiating from 
        # returned mongo document
        if type(d) == type(datetime.datetime.now()):
            return d
        else:
            return datetime.datetime.utcfromtimestamp(d)

    def get_document(self):
        doc = {}
        for k,v in self.__dict__.items():
            if k.startswith('_'):
                continue
            doc[k] = v
            
        for p in self._doc_properties:
            doc[p] = getattr(self, '%s' % p)
        
        return doc
        
    def get_key(self):
        # Get the cassandra row key for an object
        return '%s%s%s%s%s%s%s%s%s' % (
            self.device, self._key_delimiter,
            self.path, self._key_delimiter,
            self.oid, self._key_delimiter,
            self.freq, self._key_delimiter,
            self.ts.year
        )
        
    def get_meta_key(self):
        # Get a "metadata row key" - metadata don't have timestamps
        # but some other objects need access to this to look up
        # entires in the metadata_cache.
        return '%s%s%s%s%s%s%s' % (
            self.device, self._key_delimiter,
            self.path, self._key_delimiter,
            self.oid, self._key_delimiter,
            self.freq
        )
        
    def get_path(self):
        p = {}
        for k,v in self.__dict__.items():
            if k not in ['device', 'oidset', 'oid', 'path']:
                continue
            p[k] = v
        return p
        
    def get_path_tuple(self):
        p = self.get_path()
        return (p['device'], p['oidset'], p['oid'], p['path'])
        
    def ts_to_unixtime(self, t='ts'):
        ts = getattr(self, t)
        return calendar.timegm(ts.utctimetuple())
        
        
class RawData(DataContainerBase):
    """
    Container for raw data rows.  Can be instantiated from args when
    reading from persist queue, or via **kw when reading data back
    out of mongo.
    """
    _doc_properties = ['ts']
    
    def __init__(self, device=None, oidset=None, oid=None, path=None,
            ts=None, val=None, freq=None, _id=None):
        DataContainerBase.__init__(self, device, oidset, oid, path, _id)
        self._ts = None
        self.ts = ts
        self.val = val
        self.freq = freq
        
    @property
    def ts(self):
        return self._ts
        
    @ts.setter
    def ts(self, value):
        self._ts = self._handle_date(value)
        
    @property
    def min_last_update(self):
        return self.ts_to_unixtime() - self.freq * 40
        
    @property
    def slot(self):
        return (self.ts_to_unixtime() / self.freq) * self.freq
    
        
class Metadata(DataContainerBase):
    
    _doc_properties = ['min_ts', 'last_update']
    
    def __init__(self, device=None, oidset=None, oid=None, path=None, _id=None,
            last_update=None, last_val=None, min_ts=None, freq=None):
        DataContainerBase.__init__(self, device, oidset, oid, path, _id)
        self._min_ts = self._last_update = None
        self.last_update = last_update
        self.last_val = last_val
        self.min_ts = min_ts
        self.freq = freq
        
    @property
    def min_ts(self):
        return self._min_ts
        
    @min_ts.setter
    def min_ts(self, value):
        self._min_ts = self._handle_date(value)
    
    @property
    def last_update(self):
        return self._last_update
        
    @last_update.setter
    def last_update(self, value):
        self._last_update = self._handle_date(value)
        
    def refresh_from_raw(self, data):
        if self.min_ts > data.ts:
            self.min_ts = data.ts
        self.last_update = data.ts
        self.last_val = data.val
        

class BaseRateBin(DataContainerBase):
    
    _doc_properties = ['ts']
    
    def __init__(self, device=None, oidset=None, oid=None, path=None, _id=None, 
            ts=None, freq=None, val=None, is_valid=1):
        DataContainerBase.__init__(self, device, oidset, oid, path, _id)
        self._ts = None
        self.ts = ts
        self.freq = freq
        self.val = val
        self.is_valid = is_valid

    @property
    def ts(self):
        return self._ts

    @ts.setter
    def ts(self, value):
        self._ts = self._handle_date(value)
        
    @property
    def avg(self):
        return self.val / self.freq
    

class AggregationBin(BaseRateBin):
    
    def __init__(self, device=None, oidset=None, oid=None, path=None, _id=None,
            ts=None, freq=None, val=None, base_freq=None, count=None, 
            min=None, max=None):
        BaseRateBin.__init__(self, device, oidset, oid, path, _id, ts, freq, val)
        
        self.count = count
        self.min = min
        self.max = max
        self.base_freq = base_freq
        
    @property
    def avg(self):
        return self.val / (self.count * self.base_freq)
