from typing import Optional

from PyQt5.Qt import QTimer, QObject, pyqtSignal

from UM.Logger import Logger
from UM.Settings import ContainerRegistry
from UM.Settings import InstanceContainer


class MaterialGroup:
    __slots__ = ("name", "root_material_node", "derived_material_node_list")

    def __init__(self, name):
        self.name = name
        self.root_material_node = None
        self.derived_material_node_list = []


class MaterialNode:
    __slots__ = ("metadata", "container", "material_map", "children_map")

    def __init__(self, metadata = None):
        self.metadata = metadata
        self.container = None
        self.material_map = {}
        self.children_map = {}

    def getContainer(self) -> "InstanceContainer":
        if not self.container:
            from cura.Settings.CuraContainerRegistry import CuraContainerRegistry
            containers = CuraContainerRegistry.getInstance().findContainers(id = self.metadata["id"])
            if not containers:
                raise RuntimeError("Cannot find container with ID [%s]" % self.metadata["id"])
            self.container = containers[0]
        return self.container


class MaterialManager(QObject):

    materialsUpdated = pyqtSignal()

    def __init__(self, container_registry, parent = None):
        super().__init__(parent)
        self._container_registry = container_registry  # type: ContainerRegistry

        self._material_group_map = dict()  # root_material_id -> MaterialGroup
        self._diameter_machine_variant_material_map = dict()  # diameter -> dict(machine_definition_id -> MaterialNode)

        # The machine definition ID for the non-machine-specific materials.
        # This is used as the last fallback option if the given machine-specific material(s) cannot be found.
        self._default_machine_definition_id = "fdmprinter"

        self._update_timer = QTimer(self)
        self._update_timer.setInterval(300)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._updateTables)

        self._container_registry.containerMetaDataChanged.connect(self._onContainerMetadataChanged)
        self._container_registry.containerAdded.connect(self._onContainerMetadataChanged)
        self._container_registry.containerRemoved.connect(self._onContainerMetadataChanged)

    def initialize(self):
        # Find all materials and put them in a matrix for quick search.
        material_metadata_list = self._container_registry.findContainersMetadata(type = "material")

        self._material_group_map = {}
        self._diameter_machine_variant_material_map = {}

        # Table #1
        #    root_material_id -> MaterialGroup
        for material_metadata in material_metadata_list:
            material_id = material_metadata["id"]
            # We don't store empty material in the lookup tables
            if material_id == "empty_material":
                continue

            root_material_id = material_metadata.get("base_file")
            if root_material_id not in self._material_group_map:
                self._material_group_map[root_material_id] = MaterialGroup(root_material_id)
            group = self._material_group_map[root_material_id]

            # We only add root materials here
            if material_id == root_material_id:
                group.root_material_node = MaterialNode(material_metadata)
            else:
                new_node = MaterialNode(material_metadata)
                group.derived_material_node_list.append(new_node)

        # Table #2
        #    "machine" -> "variant_name" -> "root material ID" -> specific material InstanceContainer
        # Construct the "machine" -> "variant" -> "root material ID" -> specific material InstanceContainer
        for material_metadata in material_metadata_list:
            # We don't store empty material in the lookup tables
            if material_metadata["id"] == "empty_material":
                continue

            root_material_id = material_metadata["base_file"]
            definition = material_metadata["definition"]
            approximate_diameter = material_metadata["approximate_diameter"]

            if approximate_diameter not in self._diameter_machine_variant_material_map:
                self._diameter_machine_variant_material_map[approximate_diameter] = {}

            machine_variant_material_map = self._diameter_machine_variant_material_map[approximate_diameter]
            if definition not in machine_variant_material_map:
                machine_variant_material_map[definition] = MaterialNode()

            machine_node = machine_variant_material_map[definition]
            variant_name = material_metadata.get("variant_name")
            if not variant_name:
                # if there is no variant, this material is for the machine, so put its metadata in the machine node.
                machine_node.material_map[root_material_id] = MaterialNode(material_metadata)
            else:
                # this material is variant-specific, so we save it in a variant-specific node under the
                # machine-specific node
                if variant_name not in machine_node.children_map:
                    machine_node.children_map[variant_name] = MaterialNode()

                variant_node = machine_node.children_map[variant_name]
                if root_material_id not in variant_node.material_map:
                    variant_node.material_map[root_material_id] = MaterialNode(material_metadata)
                else:
                    # Sanity check: make sure we don't have duplicated variant-specific materials for the same machine
                    raise RuntimeError("Found duplicate variant name [%s] for machine [%s] in material [%s]" %
                                       (variant_name, definition, material_metadata["id"]))

        self.materialsUpdated.emit()

    def _updateTables(self):
        self.initialize()

    def _onContainerMetadataChanged(self, container):
        self._onContainerChanged(container)

    def _onContainerChanged(self, container):
        container_type = container.getMetaDataEntry("type")
        if container_type != "material":
            return

        # TODO: update the cache table
        self._update_timer.start()

    def getMaterialGroup(self, root_material_id: str) -> Optional[MaterialGroup]:
        return self._material_group_map.get(root_material_id)

    def _test_metadata(self):
        # print all metadata
        import os
        with open("c:/workspace/guid_map.txt", "w", encoding = "utf-8") as f:
            for machine_id, node in self._guid_to_root_materials_map.items():
                f.write((" -   %s   ->   %s" % (machine_id, node.metadata["id"])) + os.linesep)

        if False:
            with open("c:/workspace/material_map.txt", "w", encoding = "utf-8") as f:
                for machine_id in self._machine_variant_material_map:
                    f.write((" ->   %s" % machine_id) + os.linesep)

        test_cases = [{"machine": "ultimaker3", "variant": "AA 0.4", "material": "generic_pla", "diameter": 2.85},
                      {"machine": "ultimaker2_plus", "variant": None, "material": "generic_abs", "diameter": 2.85},
                      {"machine": "fdmprinter", "variant": None, "material": "generic_cpe", "diameter": 2.85},
                      {"machine": "fdmprinter", "variant": None, "material": "generic_abs_175", "diameter": 2.85},
                      {"machine": "fdmprinter", "variant": None, "material": "generic_nylon", "diameter": 1.75},
                      {"machine": "fdmprinter", "variant": None, "material": "generic_nylon_175", "diameter": 1.75},
                      ]
        for tc in test_cases:
            result = self.getMaterial(tc['machine'],
                                      tc['variant'],
                                      tc['diameter'],
                                      tc['material'])
            tc['result_id'] = result.getId() if result else "None"
            Logger.log("d", "!!!!!!!! MaterialManager test: %s", tc)

        # test available materials
        with open("c:/workspace/test.txt", "w", encoding="utf-8") as f:
            for tc in test_cases:
                result = self.getAvailableMaterials(tc['machine'],
                                                    tc['variant'],
                                                    tc['diameter'])
                f.write("--- [%s] [%s] [%s]:" % (tc['machine'], tc['variant'], tc['diameter']) + "\n")
                for r, md in result.items():
                    f.write("     -   %s  ->  %s" % (r, md["id"]) + "\n")

    #
    # Gets all root material IDs that's suitable for the given setup.
    #
    def getAvailableMaterials(self, machine_definition_id: str, variant_name: Optional[str], diameter: float) -> dict:
        # round the diameter to get the approximate diameter
        rounded_diameter = str(round(diameter))
        if rounded_diameter not in self._diameter_machine_variant_material_map:
            Logger.log("i", "Cannot find materials with diameter [%s] (rounded to [%s])", diameter, rounded_diameter)
            return {}

        # If there are variant materials, get the variant material
        machine_variant_material_map = self._diameter_machine_variant_material_map[rounded_diameter]
        machine_node = machine_variant_material_map.get(machine_definition_id)
        variant_node = None
        if machine_node is None:
            machine_node = machine_variant_material_map.get(self._default_machine_definition_id)
        if variant_name is not None and machine_node is not None:
            variant_node = machine_node.children_map.get(variant_name)

        # Fallback mechanism of finding materials:
        #  1. variant-specific material
        #  2. machine-specific material
        #  3. generic material (for fdmprinter)
        material_id_metadata_dict = {}
        if variant_node is not None:
            material_id_metadata_dict = {mid: node.metadata for mid, node in variant_node.material_map.items()}

        # Fallback: machine-specific materials, including "fdmprinter"
        if not material_id_metadata_dict:
            if machine_node is not None:
                material_id_metadata_dict = {mid: node.metadata for mid, node in machine_node.material_map.items()}

        return material_id_metadata_dict

    #
    # Gets the material InstanceContainer for the given extruder and machine with the given material name.
    # Returns None if:
    #  1. the given machine doesn't have materials;
    #  2. cannot find any material InstanceContainers with the given settings.
    #
    def getMaterial(self, machine_definition_id: str, variant_name: Optional[str], diameter: float, root_material_id: str) -> Optional["InstanceContainer"]:
        # round the diameter to get the approximate diameter
        rounded_diameter = str(round(diameter))
        if rounded_diameter not in self._diameter_machine_variant_material_map:
            Logger.log("i", "Cannot find materials with diameter [%s] (rounded to [%s]) for root material id [%s]",
                       diameter, rounded_diameter, root_material_id)
            return None

        # If there are variant materials, get the variant material
        machine_variant_material_map = self._diameter_machine_variant_material_map[rounded_diameter]
        machine_node = machine_variant_material_map.get(machine_definition_id)
        variant_node = None

        # Fallback for "fdmprinter" if the machine-specific materials cannot be found
        if machine_node is None:
            machine_node = machine_variant_material_map.get(self._default_machine_definition_id)
        if machine_node is not None and variant_name is not None:
            variant_node = machine_node.children_map.get(variant_name)

        # Fallback mechanism of finding materials:
        #  1. variant-specific material
        #  2. machine-specific material
        #  3. generic material (for fdmprinter)
        material = None
        if variant_node is not None:
            if root_material_id in variant_node.material_map:
                material_node = variant_node.material_map.get(root_material_id)
                if material_node is not None:
                    material = self._getContainerOnNode(material_node)

        # Fallback: machine-specific materials, including "fdmprinter"
        if material is None:
            if machine_node is not None:
                material_node = machine_node.material_map.get(root_material_id)
                if material_node is not None:
                    material = self._getContainerOnNode(material_node)

        return material

    #
    # Gets the material InstanceContainer on this MaterialNode.
    # If the container has not been loaded yet, it will be loaded.
    def _getContainerOnNode(self, node: MaterialNode) -> "InstanceContainer":
        if node.container is None:
            container_id = node.metadata["id"]
            container_list = self._container_registry.findInstanceContainers(id = container_id)
            if not container_list:
                raise RuntimeError(
                    "Cannot lazy-load material container [%s], cannot be found in ContainerRegistry" % container_id)
            node.container = container_list[0]
        return node.container
