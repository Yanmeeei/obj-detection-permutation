from device import Device
import pandas as pd
from layer import Layer


class Simulator(object):

    def __init__(self,
                 dep_filename,
                 prof_filenames,
                 bandwidth=200,
                 device_names=None,
                 priority_filename=None,
                 part_filename=None,
                 ignore_latency=False):
        super().__init__()
        self.bandwidth = bandwidth

        self.ignore_latency = ignore_latency
        self.results = []

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
        print(f"Device parallel = {parallel}")
        if device_names is None:
            # TODO: should #device determined by prof?
            self.device_names = [str(i) for i in range(len(prof_filenames))]
        for name, prof_filename in zip(self.device_names, prof_filenames):
            self.devices[name] = Device(name, prof_filename, parallel=parallel)

        # load dependencies and initialize all Layers
        self.load_dependencies(dep_filename)
        self.load_macs_size(prof_filename)

        # if priority file is not given, init with even priorities
        if priority_filename is not None:
            self.load_priorities(priority_filename)
        else:
            for name in list(self.layers.keys()):
                self.priorities[name] = 1

        self.load_partitions(part_filename)  # Intermediate result of partition, now load from handcoded csv
        # self.partition(part_filename)

        print(self.device_names)
        for device in list(self.devices.values()):
            # TODO: Now exec has not much to do with assigned layers
            print(f"Device name: {device.name}, with layers: {device.assigned_layer}")
        print("{:<15} {:<15}".format("layer", "device"))
        for layer in list(self.layers.values()):
            print("{:<15} {:<15}".format(layer.name, layer.device_id))
        print(f"Layer priority: {self.priorities}")

        self.simulate()

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
        # TODO: Here size is with layers. If necessary, can be with dependencies.
        df_list = pd.read_csv(prof_filename).values.tolist()
        for layername, time, cpu, cuda, size, macs in df_list:
            self.layers[layername].size = size
            self.layers[layername].macs = macs

    def load_priorities(self, priority_filename):
        priorities = pd.read_csv(priority_filename).values.tolist()
        for layername, priority in priorities:
            self.priorities[layername] = priority
            self.layers[layername].pr_max = priority

    def load_partitions(self, part_filename):
        partitions = pd.read_csv(part_filename).values.tolist()
        for layername, device_id in partitions:
            self.layers[layername].device_id = str(device_id)
            self.devices[str(device_id)].assigned_layer.append(layername)

    def clean_up(self):
        for name, layer in self.layers.items():
            layer.end_time = 0
            # layer.device_id = None
        for name, device in self.devices.items():
            device.available_time = 0
            device.cur_time = 0

    def decide_one_layer(self, cur_layer_name):
        print(f"Begin analyzing layer {cur_layer_name}. ")

        # min(max(max(end_time + transfer_time), device_clock) + execution_time)
        device_results = []

        sorted_device_names = list(self.devices.keys())
        sorted_device_names = sorted(sorted_device_names, key=lambda e: self.devices[e].available_time)
        for device_name in sorted_device_names:
            device = self.devices[device_name]
            dependency_arrival_timepool = []
            for dep_name in self.layers[cur_layer_name].dependencies:
                dep_layer = self.layers[dep_name]
                transfer_latency = 0
                if (not self.ignore_latency) and dep_layer.device_id != device.name:
                    transfer_latency = dep_layer.size / self.bandwidth

                end_time = dep_layer.end_time + transfer_latency + device.time[cur_layer_name]
                dependency_arrival_timepool.append(end_time)
            dependency_arrival_timepool.append(device.available_time + device.time[cur_layer_name])
            print(f"The arrival time pool of dependencies on device {device_name} is {dependency_arrival_timepool}")
            device_results.append(max(dependency_arrival_timepool))
        print(f"==>>decision pool(clock time): {device_results}")
        min_value = min(device_results)
        decision = device_results.index(min_value)
        decision = sorted_device_names[decision]
        self.layers[cur_layer_name].end_time = min_value
        self.layers[cur_layer_name].completed = True
        self.layers[cur_layer_name].device_id = decision
        self.devices[decision].available_time = min_value
        print(f"Decision for layer {cur_layer_name}: executed on device {decision}, end time {min_value}\n")
        # self.partitions.write(f"{cur_layer_name},{decision}\n")
        return decision

    def device_exec(self, cur_layer_name):
        """
        Update device current time.
        Returns the next layers.
        """
        if cur_layer_name == "output":
            return
        else:
            print("")
            cur_layer = self.layers[cur_layer_name]
            for dep in cur_layer.dependencies:
                if not self.layers[dep].completed:
                    print(f"Dependency for {cur_layer_name} not satisfied.")
                    return

            print(f"Device {cur_layer.device_id} is running: {cur_layer.name}")
            device = self.devices[str(cur_layer.device_id)]
            dependency_arrival_timepool = []
            for dep in cur_layer.dependencies:
                dep_layer = self.layers[dep]
                transfer_latency = 0
                if (not self.ignore_latency) and str(dep_layer.device_id) != device.name:
                    transfer_latency = dep_layer.size / self.bandwidth
                    if dep == "d3_conv1":
                        a = 1
                print(f"Receiving layer {dep} data from device {dep_layer.device_id}, "
                      f"starting at {dep_layer.end_time:.4f}, latency {transfer_latency}.")
                end_time = dep_layer.end_time + transfer_latency
                dependency_arrival_timepool.append(end_time)

            device = self.devices[str(cur_layer.device_id)]
            dependency_arrival_timepool.append(device.available_time)
            end_time = max(dependency_arrival_timepool) + device.time[cur_layer_name]
            self.layers[cur_layer_name].end_time = end_time
            print(f"Layer {cur_layer_name} is executed from {end_time - device.time[cur_layer_name]:.4f} to {end_time:.4f}")
            self.layers[cur_layer_name].completed = True
            self.devices[str(cur_layer.device_id)].available_time = end_time

            if self.priorities is None:
                print("NO priority file specified. ")
            else:
                print("Sorting criteria: priorities")
            cur_layer.next = sorted(cur_layer.next, key=lambda e: self.layers[e].pr_max, reverse=True)

            print(f"Sorted branches: {cur_layer.next}")
            for next_layer_name in cur_layer.next:
                if self.layers[next_layer_name].completed:
                    continue
                if next_layer_name == "output":
                    self.time_result[cur_layer_name] = cur_layer.end_time
                    continue
                self.device_exec(next_layer_name)

    def simulate(self):
        self.clean_up()

        print(f"\n\033[30;44m=========Simulatinginging=========\033[0m")

        self.layers["input"].end_time = 0
        self.layers["input"].device_id = 0

        self.device_exec("input")

        print(f"\n\033[30;42m=========Time Result=========\033[0m")
        print("{:<15} {:<15}".format("output_layer", "time (s)"))
        for key, value in self.time_result.items():
            print("{:<15} {:<15,.5f}".format(key, value))

        # print(f"\n\033[30;42m=========Time Result per Device=========\033[0m")
        # print("{:<15} {:<15}".format("device", "time (s)"))
        # for key, value in self.time_result_seg.items():
        #     print("{:<15} {:<15,.5f}".format(key, value))

        print(f"\n\033[30;42m=========Mem Result=========\033[0m")
        print("{:<15} {:<15} {:<15} {:<15} {:<15}".format("device", "cpu sum (MB)", "cpu peak (MB)", "cuda sum (MB)",
                                                          "cuda peak (MB)"))
        for name, device in self.devices.items():
            device.get_mem_consumption()

        print(f"\n\033[30;42m=========MACs Result=========\033[0m")
        print("{:<15} {:<15} {:<15}".format("device", "macs sum (M)", "macs peak (M)"))
        for name, device in self.devices.items():
            device.get_macs()
        # print(self.results)
