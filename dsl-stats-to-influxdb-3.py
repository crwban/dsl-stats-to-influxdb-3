import telnetlib as tn
import time as t
import datetime as dt
import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
import sdnotify
from configparser import ConfigParser
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

influx_ip = None
influx_port = None
influx_token = None
influx_org = None
influx_bucket = None
modem_ip = None
modem_username = None
modem_password = None

class ParsedStats:
    def __init__(self, conn_stats_output, system_uptime):
        conn_stats_output_split = conn_stats_output.decode().split("\r\n")
        if len(conn_stats_output_split) == 176:
            self.connection_up = True
            max_line = conn_stats_output_split[5].replace("Max:\tUpstream rate = ", "")
            max_split = max_line.split(", Downstream rate = ")
            self.max_up = int(max_split[0].replace(" Kbps", ""))
            self.max_down = int(max_split[1].replace(" Kbps", ""))
            current_line = conn_stats_output_split[6].replace("Bearer:\t0, Upstream rate = ", "")
            current_split = current_line.split(", Downstream rate = ")
            self.current_up = int(current_split[0].replace(" Kbps", ""))
            self.current_down = int(current_split[1].replace(" Kbps", ""))
            snr_line = conn_stats_output_split[16].replace("SNR (dB):\t ", "")
            snr_split = snr_line.split("\t\t ")
            self.snr_down = float(snr_split[0])
            self.snr_up = float(snr_split[1])
            attn_line = conn_stats_output_split[17].replace("Attn(dB):\t ", "")
            attn_split = attn_line.split("\t\t ")
            self.attn_down = float(attn_split[0])
            self.attn_up = float(attn_split[1])
            pwr_line = conn_stats_output_split[18].replace("Pwr(dBm):\t ", "")
            pwr_split = pwr_line.split("\t\t")
            self.pwr_down = float(pwr_split[0])
            self.pwr_up = float(pwr_split[1])
            interleaving_line = conn_stats_output_split[28].replace("D:\t\t", "")
            interleaving_split = interleaving_line.split("\t\t")
            self.int_down = int(interleaving_split[0])
            self.int_up = int(interleaving_split[1])
            err_secs_line = conn_stats_output_split[98].replace("ES:\t\t", "")
            err_secs_split = err_secs_line.split("\t\t")
            self.err_secs_up = int(err_secs_split[0])
            self.err_secs_down = int(err_secs_split[1])
            serious_err_secs_line = conn_stats_output_split[99].replace("SES:\t\t", "")
            serious_err_secs_split = serious_err_secs_line.split("\t\t")
            self.serious_err_secs_up = int(serious_err_secs_split[0])
            self.serious_err_secs_down = int(serious_err_secs_split[1])
            unavailable_secs_line = conn_stats_output_split[100].replace("UAS:\t\t", "")
            unavailable_secs_split = unavailable_secs_line.split("\t\t")
            self.unavailable_secs_up = int(unavailable_secs_split[0])
            self.unavailable_secs_down = int(unavailable_secs_split[1])
            self.available_secs = int(conn_stats_output_split[101].replace("AS:\t\t", ""))
        else:
            self.connection_up = False
        system_uptime_split = system_uptime.decode().split("\r\n")
        self.system_uptime = float(system_uptime_split[1].split(" ")[0])


def main():
    while True:
        timestamp = dt.datetime.fromtimestamp(t.time()).strftime("%Y-%m-%dT%H:%M:%S")
        try:
            parsed_stats = retrieve_stats()
            send_stats_to_influxdb(parsed_stats, timestamp)
        except Exception as ex:
            ex_type, value, traceback = sys.exc_info()
            filename = os.path.split(traceback.tb_frame.f_code.co_filename)[1]
            logger.error("{0}, {1}: {2}".format(filename, traceback.tb_lineno, ex))
        t.sleep(60)


def retrieve_stats():
    try:
        tnconn = tn.Telnet(modem_ip)
        tnconn.read_until(b"Login:")
        tnconn.write("{0}\n".format(modem_username).encode())
        tnconn.read_until(b"Password:")
        tnconn.write("{0}\n".format(modem_password).encode())
        tnconn.read_until(b"ATP>")
        tnconn.write(b"sh\n")
        tnconn.read_until(b"#")
        tnconn.write(b"xdslcmd info --stats\n")
        stats_output = tnconn.read_until(b"#")
        tnconn.write(b"cat /proc/uptime\n")
        system_uptime = tnconn.read_until(b"#")
        parsed_stats = ParsedStats(stats_output, system_uptime)
        return parsed_stats
    except Exception:
        raise

def make_point(field_name, stat, timestamp):
        return Point("connection").field(field_name, stat).time(timestamp)

def get_points(parsedStats, timestamp):
    try:
        if parsedStats.connection_up:
            return [
                make_point("AttDown", parsedStats.attn_down, timestamp),
                make_point("AttnUp", parsedStats.attn_up, timestamp),
                make_point("AvailableSecs", parsedStats.available_secs, timestamp),
                make_point("CurrDown", parsedStats.current_down, timestamp),
                make_point("CurrUp", parsedStats.current_up, timestamp),
                make_point("ErrSecsDown", parsedStats.err_secs_down, timestamp),
                make_point("ErrSecsUp", parsedStats.err_secs_up, timestamp),
                make_point("InterleavingDown", parsedStats.int_down, timestamp),
                make_point("InterleavingUp", parsedStats.int_up, timestamp),
                make_point("MaxDown", parsedStats.max_down, timestamp),
                make_point("MaxUp", parsedStats.max_up, timestamp),
                make_point("PwrDown", parsedStats.pwr_down, timestamp),
                make_point("PwrUp", parsedStats.pwr_up, timestamp),
                make_point("SeriousErrSecsDown", parsedStats.serious_err_secs_down, timestamp),
                make_point("SeriousErrSecsUp", parsedStats.serious_err_secs_up, timestamp),
                make_point("SNRDown", parsedStats.snr_down, timestamp),
                make_point("SNRUp", parsedStats.snr_up, timestamp),
                make_point("SystemUptime", parsedStats.system_uptime, timestamp),
                make_point("UnavailableSecsDown", parsedStats.unavailable_secs_down, timestamp),
                make_point("UnavailableSecsUp", parsedStats.unavailable_secs_up, timestamp),
            ]
        else:
            return [
                make_point("AttDown", -1, timestamp),
                make_point("AttnUp", -1, timestamp),
                make_point("AvailableSecs", -1, timestamp),
                make_point("CurrDown", -1, timestamp),
                make_point("CurrUp", -1, timestamp),
                make_point("ErrSecsDown", -1, timestamp),
                make_point("ErrSecsUp", -1, timestamp),
                make_point("InterleavingDown", -1, timestamp),
                make_point("InterleavingUp", -1, timestamp),
                make_point("MaxDown", -1, timestamp),
                make_point("MaxUp", -1, timestamp),
                make_point("PwrDown", -1, timestamp),
                make_point("PwrUp", -1, timestamp),
                make_point("SeriousErrSecsDown", -1, timestamp),
                make_point("SeriousErrSecsUp", -1, timestamp),
                make_point("SNRDown", -1, timestamp),
                make_point("SNRUp", -1, timestamp),
                make_point("SystemUptime", parsedStats.system_uptime, timestamp),
                make_point("UnavailableSecsDown", -1, timestamp),
                make_point("UnavailableSecsUp", -1, timestamp),
            ]
    except Exception:
        raise

def send_stats_to_influxdb(parsedStats, timestamp):
    client =  InfluxDBClient(url="http://"+influx_ip+":"+str(influx_port), token=influx_token, org=influx_org,verify_ssl=False)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    try:
        write_api.write(bucket=influx_bucket, record=get_points(parsedStats, timestamp))
    except Exception as error:
        print(error)

n = sdnotify.SystemdNotifier()
n.notify("READY=1")

config_path = "dsl-stats-to-influxdb-3_config.ini"

config = ConfigParser()
config.read(config_path)

if "InfluxDB" in config:
    influx_ip = config["InfluxDB"].get("ip-address")
    influx_port = config["InfluxDB"].get("port")
    influx_token = config["InfluxDB"].get("token")
    influx_bucket = config["InfluxDB"].get("bucket")
    influx_org = config["InfluxDB"].get("org")
    if influx_port is not None:
        influx_port = int(influx_port)
else:
    raise Exception("Wasn't able to find the 'InfluxDB' section in the config")

if influx_ip is None or influx_port is None or influx_token is None or influx_org is None or influx_bucket is None:
    raise Exception("At least one piece of Influx connection information is missing from the config")

if "Modem" in config:
    modem_ip = config["Modem"].get("ip-address")
    modem_username = config["Modem"].get("username")
    modem_password = config["Modem"].get("password")
else:
    raise Exception("Wasn't able to find the 'Modem' section in the config")

if modem_ip is None or modem_username is None or modem_password is None:
    raise Exception("At least one piece of Modem connection information is missing from the config")

logger = logging.getLogger("Rotating Error Log")
logger.setLevel(logging.ERROR)
handler = TimedRotatingFileHandler("dsl-stats-to-influxdb-3.log", when="midnight", backupCount=5)
formatter = logging.Formatter(fmt="%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
main()
