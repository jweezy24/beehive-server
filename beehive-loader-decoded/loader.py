from cassandra.cluster import Cluster
from datetime import datetime
import pika
import os
import json


BEEHIVE_DEPLOYMENT = os.environ.get('BEEHIVE_DEPLOYMENT', '/')


cluster = Cluster(contact_points=['beehive-cassandra'])
session = cluster.connect('waggle')
query = 'INSERT INTO sensor_data_decoded (node_id, date, ingest_id, meta_id, timestamp, data_set, sensor, parameter, data, unit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
prepared = session.prepare(query)


def process_message(ch, method, properties, body):
    dictData = json.loads(body.decode())

    # same for each parameter:value pair
    sampleDatetime = datetime.utcfromtimestamp(float(properties.timestamp) / 1000.0)
    # TODO Validate / santize node_id here.
    node_id = properties.reply_to
    sampleDate = sampleDatetime.strftime('%Y-%m-%d')
    ingest_id = 0
    meta_id = 0
    timestamp = int(properties.timestamp)
    data_set = properties.app_id
    sensor = properties.type
    unit = 'NO_UNIT'

    for k in dictData.keys():
        parameter = k
        data = str(dictData[k])
        session.execute(prepared, (node_id, sampleDate, ingest_id, meta_id, timestamp, data_set, sensor, parameter, data, unit))

    ch.basic_ack(delivery_tag=method.delivery_tag)


connection = pika.BlockingConnection(pika.ConnectionParameters(
    host='beehive-rabbitmq',
    port=5672,
    virtual_host=BEEHIVE_DEPLOYMENT,
    credentials=pika.PlainCredentials(
        username='loader_decoded',
        password='waggle',
    ),
    connection_attempts=10,
    retry_delay=3.0))

channel = connection.channel()
# channel.basic_qos(prefetch_count=1)
channel.basic_consume(process_message, queue='db-decoded')
channel.start_consuming()
