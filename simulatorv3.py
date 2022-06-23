from device import Device
import pandas as pd
from layer import Layer
from itertools import combinations_with_replacement, product


class Simulator(object):

    def __init__(self,
                 dep_filename,
                 prof_filenames,
                 bandwidth=200,
                 device_names=None,
                 priority_filename=None,
                 ignore_latency=False,
                 detailed=False,
                 feedback_interval=0.1):
        super().__init__()
        self.bandwidth = bandwidth

        self.ignore_latency = ignore_latency
        self.results = []
        self.cur_result = 0
        self.best_result = 10000

        self.current_device = 0  # spin
        self.device_names = []  # spinning through all devices
        self.devices = {}  # Dictionary of Device objects: device_name -> Device object
        self.layers = {}  # Dictionary of Layer objects: layername -> Layer objects
        self.priorities = {}  # Dictionary of integers: layername -> integer
        self.cut_points = {}

        self.time_result = {}
        self.mem_result = {}
        self.time_result_seg = {}

        self.stack = []  # for DFS
        self.waiting_queue = []  # for DFS: when layer cannot be explored due to
        #      dependencies are not fulfilled
        #      need to change device

        # load and initialize devices
        parallel = True
        # print(f"Device parallel = {parallel}")
        if device_names is None:
            self.device_names = [str(i) for i in range(len(prof_filenames))]
        for name, prof_filename in zip(self.device_names, prof_filenames):
            self.devices[name] = Device(name, prof_filename, parallel=parallel)

        # load dependencies and initialize all Layers
        self.load_dependencies(dep_filename)

        # if priority file is not given, init with even priorities
        if priority_filename is not None:
            self.load_priorities(priority_filename)
        else:
            for name in list(self.layers.keys()):
                self.priorities[name] = 1

        self.load_macs_size(prof_filenames[0])

        num_layers = len(self.layers)
        device_list = list(range(0, len(prof_filenames), 1))
        comb = product(device_list, repeat=num_layers)
        num_iter = 0
        total_iter = len(prof_filenames) ** num_layers
        progress = 0
        best_assignment = None
        for c in comb:
            self.load_partitions(c)
            num_iter += 1
            self.simulate()
            if detailed:
                print(f"{c}, {self.cur_result:.6f}")
            elif (num_iter - progress * feedback_interval * total_iter) / total_iter >= feedback_interval:
                progress += 1
                print(f"==>>{progress * feedback_interval:.4f}%")
            if self.cur_result < self.best_result:
                self.best_result = self.cur_result
                best_assignment = c

        self.load_partitions(best_assignment)
        print(f"\n==>>Best result: {self.best_result} s")

        print("\n================DEVICE ASSIGNMENT================")
        print("{:<15} {:<15}".format("layer name", "device"))
        for layer_name, layer in self.layers.items():
            print("{:<15} {:<15}".format(layer_name, layer.device_id))
        print("===============================================\n")

    def load_dependencies(self, dep_filename):
        """
        Dependencies file has the following format for each line:
            source, destination, size (temporarily remove shape)
        Use source layer name as the name of the data
        Update Layer's dependencies and next lists
        """
        df_list = pd.read_csv(dep_filename).values.tolist()
        for entry in df_list:
            src = entry[0]
            dst = entry[1]
            if src not in self.layers.keys():
                self.layers[src] = Layer(src)
            if dst not in self.layers.keys():
                self.layers[dst] = Layer(dst)
            self.layers[src].next.append(dst)
            self.layers[dst].dependencies.append(src)

    def load_macs_size(self, prof_filename):
        df_list = pd.read_csv(prof_filename).values.tolist()
        for layername, time, cpu, cuda, size, macs in df_list:
            self.layers[layername].size = size
            self.layers[layername].macs = macs

    def load_priorities(self, priority_filename):
        priorities = pd.read_csv(priority_filename).values.tolist()
        for layername, priority in priorities:
            self.priorities[layername] = priority
            self.layers[layername].pr_max = priority

    def load_partitions(self, comb_list):
        """
        """
        for (layer_name, layer), device_id in zip(self.layers.items(), comb_list):
            self.layers[layer_name].device_id = str(device_id)
            self.devices[str(device_id)].assigned_layer.append(layer_name)

    def clean_up(self):
        for name, layer in self.layers.items():
            layer.end_time = 0
            layer.completed = False
        for name, device in self.devices.items():
            device.available_time = 0
            device.cur_time = 0

    def device_exec(self, cur_layer_name):
        """
        Update device current time.
        Returns the next layers.
        """
        if cur_layer_name == "output":
            return
        else:
            cur_layer = self.layers[cur_layer_name]
            for dep in cur_layer.dependencies:
                if not self.layers[dep].completed:
                    return

            device = self.devices[str(cur_layer.device_id)]
            dependency_arrival_timepool = []
            for dep in cur_layer.dependencies:
                dep_layer = self.layers[dep]
                transfer_latency = 0
                if (not self.ignore_latency) and str(dep_layer.device_id) != device.name:
                    transfer_latency = dep_layer.size / self.bandwidth
                end_time = dep_layer.end_time + transfer_latency
                dependency_arrival_timepool.append(end_time)

            device = self.devices[str(cur_layer.device_id)]
            dependency_arrival_timepool.append(device.available_time)
            end_time = max(dependency_arrival_timepool) + device.time[cur_layer_name]
            self.layers[cur_layer_name].end_time = end_time
            self.layers[cur_layer_name].completed = True
            self.devices[str(cur_layer.device_id)].available_time = end_time

            for next_layer_name in cur_layer.next:
                if self.layers[next_layer_name].completed:
                    continue
                if next_layer_name == "output":
                    self.time_result[cur_layer_name] = cur_layer.end_time
                    self.results.append(cur_layer.end_time)
                    self.cur_result = cur_layer.end_time
                    continue
                self.device_exec(next_layer_name)

    def simulate(self):
        self.clean_up()

        self.layers["input"].end_time = 0
        self.layers["input"].device_id = 0

        self.device_exec("input")
