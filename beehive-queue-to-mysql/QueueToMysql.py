#!/usr/bin/env python3

import os
import sys

sys.path.append(os.path.abspath('../'))
from config import *
from waggle_protocol.protocol.PacketHandler import *
from waggle_protocol.utilities.gPickler import *
sys.path.pop()

import argparse
import binascii
import datetime
import json
import logging
from multiprocessing import Process, Manager
import MySQLdb
import pika
import time
#logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.CRITICAL)

sys.path.append("..")
sys.path.append("/usr/lib/waggle/")

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class DataProcess(Process):
    """
        This process handles all data submissions
        is_database_raw is a bool, if True, will write data to raw-db, else to decoded-db)
    """

    def __init__(self, is_database_raw = False, verbosity = 0):
        """
            Starts up the Data handling Process
        """
        super(DataProcess,self).__init__()

        self._con = None
        self._cur = None
        self._host = 'beehive'
        self._user = 'waggle'
        self._passwd = 'waggle'
        self._db = 'waggle'
        
        if is_database_raw:
            self.input_exchange = 'data-pipeline-in'
            self.queue          = 'db-raw-mysql'
            self.statement = "INSERT INTO    sensor_data_raw   (node_id, date, plugin_name, plugin_version, plugin_instance, timestamp, parameter, data) VALUES ({},{},{},{}, {},{},{},{})"
            self.function_ExtractValuesFromMessage = self.ExtractValuesFromMessage_raw
        else:
            self.input_exchange = 'plugins-out'
            self.queue          = 'db-decoded-mysql'
            self.statement = "INSERT INTO    sensor_data_decoded   (node_id, date, ingest_id, meta_id, timestamp, data_set, sensor, parameter, data, unit) VALUES ({},{},{},{}, {},{},{},{}, {})"
            self.function_ExtractValuesFromMessage = self.ExtractValuesFromMessage_decoded

        logger.info("Initializing DataProcess")

        # Set up the Rabbit connection
        #self.connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))
        #Connect to rabbitMQ
        while True:
            try:
                self.connection = pika.BlockingConnection(pika_params)
            except Exception as e:
                logger.error("QueueToMysql: Could not connect to RabbitMQ server \"%s\": %s" % (pika_params.host, e))
                time.sleep(1)
                continue
            break


        logger.info("Connected to RabbitMQ server \"%s\"" % (pika_params.host))
        self.verbosity = verbosity
        self.numInserted = 0

        self.db_connect()

        self.channel = self.connection.channel()
        self.channel.basic_qos(prefetch_count=1)
        # Declare this process's queue
        self.channel.queue_declare(self.queue)

        self.channel.queue_bind(exchange = self.input_exchange,
            queue = self.queue)

        try:
            self.channel.basic_consume(self.callback, queue=self.queue)
        except KeyboardInterrupt:
           logger.info("exiting.")
           sys.exit(0)
        except Exception as e:
           logger.error("error: %s" % (str(e)))

    def callback(self, ch, method, props, body):
        #TODO: this simply drops failed messages, might find a better solution!? Keeping them has the risk of spamming RabbitMQ
        if self.verbosity > 1:
            print('######################################')
            print('method = ', method)
            print('props = ', props)
            print('body = ', body)
        '''EXAMPLE:
            props =  <BasicProperties(['app_id=coresense:3', 'content_type=b', 'delivery_mode=2', 'reply_to=0000001e06107d97', 'timestamp=1476135836151', 'type=frame'])>
        '''
        try:
            for iValues, values in enumerate(self.function_ExtractValuesFromMessage(props, body)):
                # Send the data off to MySQL db
                print('iValues =', iValues)
                print(' values =',  values)
                self.db_insert(values)
                print('-------AFTER inserting--------')
        except Exception as e:
            values = None
            logger.error("Error inserting data: %s" % (str(e)))
            logger.error(' method = {}'.format(repr(method)))
            logger.error(' props  = {}'.format(repr(props)))
            logger.error(' body   = {}'.format(repr(body)))
            ch.basic_ack(delivery_tag = method.delivery_tag)
            return

        ch.basic_ack(delivery_tag = method.delivery_tag)
        if values:
            self.numInserted += 1
            if self.numInserted % 2 == 0:
                logger.debug('  inserted {} raw samples of data'.format(self.numInserted))

    # Parse a message of sensor data and convert to the values to be inserted into a row in the db.  NOTE: this is a generator - because the decoded messages produce multiple rows of data.
    def ExtractValuesFromMessage_raw(self, props, body):
        print('props.app_id =', props.app_id)
        versionStrings  = props.app_id.split(':')
        sampleDatetime  = datetime.datetime.utcfromtimestamp(float(props.timestamp) / 1000.0)
        sampleDate      = sampleDatetime.strftime('%Y-%m-%d')
        node_id         = props.reply_to
        #ingest_id       = props.ingest_id ##props.get('ingest_id', 0)
        #print('ingest_id: ', ingest_id)
        plugin_name     = versionStrings[0]
        plugin_version  = versionStrings[1]
        plugin_instance = '0' if (len(versionStrings) < 3) else versionStrings[2]
        timestamp       = int(props.timestamp)
        parameter       = props.type
        data            = str(binascii.hexlify(body))

        values = (node_id, sampleDate, plugin_name, plugin_version, plugin_instance, timestamp, parameter, data)

        if self.verbosity > 0:
            print('   node_id = ',          node_id         )
            print('   date = ',             sampleDate      )
            #print('   ingest_id = ',        ingest_id       )
            print('   plugin_name = ',      plugin_name     )
            print('   plugin_version = ',   plugin_version  )
            print('   plugin_instance = ',  plugin_instance )
            print('   timestamp = ',        timestamp       )
            print('   parameter = ',        parameter       )
            print('   data = ',             data            )
        yield values

    def ExtractValuesFromMessage_decoded(self, props, body):
        #(node_id, date, meta_id, timestamp, data_set, sensor, parameter, data, unit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"

        print('before loads...')
        dictData = json.loads(body.decode())
        print('dictData =', dictData)

        # same for each parameter:value pair
        sampleDatetime  = datetime.datetime.utcfromtimestamp(float(props.timestamp) / 1000.0)
        node_id         = props.reply_to
        sampleDate      = sampleDatetime.strftime('%Y-%m-%d')
        ingest_id       = 0 # props.ingest_id ##props.get('ingest_id', 0)
        #print('ingest_id: ', ingest_id)
        meta_id         = 0 #props.meta_id
        timestamp       = int(props.timestamp)
        data_set        = props.app_id
        sensor          = props.type
        unit            = 'NO_UNIT' #props.unit

        for k in dictData.keys():
            parameter      = k
            print('k = ', k)
            data           = str(dictData[k])
            print('data = ', data)

            values = (node_id, sampleDate, ingest_id, meta_id, timestamp, data_set, sensor, parameter, data, unit)

            if self.verbosity > 0:
                print('   node_id = ',          node_id     )
                print('   date = ',             sampleDate  )
                print('   ingest_id = ',        ingest_id   )
                print('   meta_id = ',          meta_id     )
                print('   timestamp = ',        timestamp   )
                print('   data_set = ',         data_set    )
                print('   sensor = ',           sensor      )
                print('   parameter = ',        parameter   )
                print('   data = ',             data        )
                print('   unit = ',             unit        )
            yield values

    def db_insert(self, values):

        if not self._cur:
            self.db_connect()

        bound_statement = self.statement.format(values)
        
        logger.debug("inserting: %s" % (str(values)))
        connection_retry_delay = 1
        while True :
            # this is long term storage
            try:
                self._cur.execute(bound_statement)
                db._con.commit()
            except TypeError as e:
                 logger.error("QueueToMysql: (TypeError) Error executing MySQL statement: %s -- values was: %s" % (str(e), str(values)) )
                 break
            except Exception as e:
                logger.error("QueueToMysql: Error (type: %s) executing MySQL statement: %s -- values was: %s" % (type(e).__name__, str(e), str(values)) )
                if "TypeError" in str(e):
                    logger.debug("detected TypeError, will ignore this message")
                    break

                self.db_connect()
                time.sleep(connection_retry_delay)
                if connection_retry_delay < 10:
                    connection_retry_delay += 1
                continue
            break
        logger.debug('db_insert() exiting...')

    def db_connect(self):
        bDone = False
        iTry = 0
        while not bDone and (iTry < 5):
            if self._con:
                try:
                    self._con.close()
                except:
                    pass
                    
            iTry2 = 0
            while not bDone and (iTry2 < 5):
                self._con = None
                self._cur = None

                iTry2 += 1
                try: # Might not immediately connect. That's fine. It'll try again if/when it needs to.
                    self._con =  MySQLdb.connect(  
                                        host=self._host,    
                                        user=self._user,       
                                        passwd=self._passwd,  
                                        db=self._db)
                    self._cur = db.cursor()
                    if self._cur:
                        bDone = True
                except:
                    logger.warning("QueueToMysql: WARNING: MySQL connection to " + self._host + " failed.")
                    logger.warning("QueueToMysql: The process will attempt to re-connect at a later time.")
                if not bDone:
                    self._con = None
                    self._cur = None
                    time.sleep(3)

    def run(self):
        self.db_connect()
        self.channel.start_consuming()

    def join(self):
        super(DataProcess,self).terminate()
        self.connection.close(0)
        if self.cluster:
            self.cluster.shutdown()


if __name__ == '__main__':
    argParser = argparse.ArgumentParser()
    argParser.add_argument('database', choices = ['raw', 'decoded'],
        help = 'which database the data is flowing to')
    argParser.add_argument('--verbose', '-v', action='count')
    args = argParser.parse_args()
    is_database_raw = args.database == 'raw'
    verbosity = 0 if not args.verbose else args.verbose

    p = DataProcess(is_database_raw, verbosity)
    p.start()

    print(__name__ + ': created process ', p)
    time.sleep(10)

    while p.is_alive():
        time.sleep(10)

    print(__name__ + ': process is dead, time to die')
    p.join()
