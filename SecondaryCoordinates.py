import copy
import json
from qgis.PyQt.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QDialog,
    QComboBox,
    QMessageBox,
)
from qgis.PyQt.QtCore import Qt, QSettings, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QStyle
from qgis.core import (QgsProject, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsCsException)
from qgis.gui import QgisInterface
from osgeo import osr


def get_transform(crs):
    """
    Returns an updated crs name and suitable QgsCoordinateTransform or
    CalcofiTransformer object for conversion from lon/lat to desired crs.
    If the crs is bad, returns None. So this is also used as a check fn.

    crs is an epsg code as an integer or string, a well-known text string,
    or the calcofi proj4 string (which QGIS will not normally accept)
    e.g., 6414, "EPSG:6414", "+proj=calcofi",
    or 'PROJCS["NAD83(2011) / California Albers...",
    """
    src_crs = QgsProject.instance().crs()
    if src_crs is None:
        # can be None at startup before a project is open
        # assume lon/lat and change as needed
        src_crs = QgsCoordinateReferenceSystem("EPSG:4326")

    if type(crs) is str:
        if crs.startswith("+proj=calcofi"):
            return ("+proj=calcofi +ellps=clrk66", CalcofiTransformer())

    # deal with the case that an integer epsg was saved as text
    try:
        crs = int(crs)
    except ValueError:
        pass

    qcrs = QgsCoordinateReferenceSystem(crs)
    if qcrs.isValid():
        if type(crs) is int:
            # if an integer epsg code was provided and qgis has accepted it,
            # convert to a string b/c settings are stored as text anyway and
            # don't want to store dups, e.g., 6414 and EPSG:6414
            crs = "EPSG:" + str(crs)
        trans = QgsCoordinateTransform(
            src_crs, qcrs, QgsProject.instance()
        )
        return (crs, trans)
    return None


class CalcofiTransformer:
    """
    QGIS will not accept the "+proj=calcofi +ellps=clrk66" proj4 string
    as a valid transform. So use proj directly via osgeo.osr to use
    CalCOFI coordinates

    This is used in place of a qgis._core.QgsCoordinateReferenceSystem
    here. Probably should have just subclassed it.
    """
    def __init__(self):
        # convert current crs from qgis to osgeo.osr
        # need to have sourceCrs and setSourceCrs methods
        # to align with QgsCoordinateReferenceSystem objects
        self.src_crs = None
        self.crs = None

        self.setSourceCrs()

    def sourceCrs(self):
        return self.src_crs

    def setSourceCrs(self, src_crs=None):
        """
        src_crs is a QgsCoordinateReferenceSystem object
        """
        if src_crs is None:
            self.src_crs = QgsProject.instance().crs()
        else:
            self.src_crs = src_crs

        if self.src_crs is None:
            # can be None at startup before a project is open
            # assume lon/lat and change as needed
            self.src_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        #ll_srs = osr.SpatialReference()
        #ll_srs.ImportFromEPSG(4326)
        src_srs = osr.SpatialReference()
        src_srs.ImportFromWkt(self.src_crs.toWkt())

        srs = osr.SpatialReference()
        srs.ImportFromProj4("+proj=calcofi +ellps=clrk66")

        self.crs = osr.CoordinateTransformation(src_srs, srs)

    def transform(self, xy):
        """
        xy is a QgsPointXY instance, usually a SecondaryCoordinates's xy
        property
        """
        try:
            line, sta, _ = self.crs.TransformPoint(xy.y(), xy.x())
        except RuntimeError as e:
            raise QgsCsException(e)
        return (line, sta)


class ConfigDialog(QDialog):
    """
    Dialog works from/to settings that it copies from the parent SecondaryCoordinates
    widget on instantiation. The pattern is to update settings in the dialog and
    then have the parent copy them back from the dialog on accept.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.settings = parent.settings

        self.setWindowTitle("Secondary Coordinate Settings")

        transform_label = QLabel("Transform:")
        self.transform_combo = QComboBox()
        self.transform_combo.setToolTip(
            """
            An EPSG code or wkt that QgsCoordinateReferenceSystem
            will understand or the CalCOFI projection, e.g.,
            6414, EPSG:6414, or +proj=calcofi
            """
        )
        self.transform_combo.setEditable(True)
        self.transform_combo.addItems([k for k in self.settings["transforms"].keys()])
        self.transform_combo.setMaxCount(10)

        transform_name_label = QLabel("Transform Label:")
        self.transform_name_edit = QLineEdit()
        self.transform_name_edit.setToolTip(
            "Label to the left of coordinates\ne.g., 'EPSG:6414' or 'Line/Station'"
        )

        x_format_label = QLabel("x format:")
        self.x_format_combo = QComboBox()
        self.x_format_combo.setToolTip(
            "Format for the x coordinate as\na standard python formatting string"
        )
        self.x_format_combo.setEditable(True)
        self.x_format_combo.addItems(self.settings["x_formats"])
        self.x_format_combo.setMaxCount(10)

        y_format_label = QLabel("y format:")
        self.y_format_combo = QComboBox()
        self.y_format_combo.setToolTip(
            "Format for the y coordinate as\na standard python formatting string"
        )
        self.y_format_combo.setEditable(True)
        self.y_format_combo.addItems(self.settings["y_formats"])
        self.y_format_combo.setMaxCount(10)

        scaler_label = QLabel("Scale by:")
        self.scaler_combo = QComboBox()
        self.scaler_combo.setEditable(True)
        self.scaler_combo.lineEdit().setInputMask("999999999")
        self.scaler_combo.setToolTip(
            "An integer scaler to convert x and y values if wanted, "
            + "e.g., 1000 for m -> km or 1852 for m -> nm"
        )
        self.scaler_combo.setEditable(True)
        self.scaler_combo.addItems(self.settings["scalers"])
        self.scaler_combo.setMaxCount(10)

        layout = QFormLayout()

        layout.addRow(transform_label, self.transform_combo)
        layout.addRow(transform_name_label, self.transform_name_edit)
        layout.addRow(x_format_label, self.x_format_combo)
        layout.addRow(y_format_label, self.y_format_combo)
        layout.addRow(scaler_label, self.scaler_combo)

        dlg_ok = QPushButton("Ok", self)
        dlg_cancel = QPushButton("Cancel", self)
        btn_lay = QHBoxLayout()
        btn_lay.addWidget(dlg_ok)
        btn_lay.addWidget(dlg_cancel)
        layout.addRow(btn_lay)

        btn_lay2 = QHBoxLayout()
        reset_btn = QPushButton("Reset To Defaults", self)
        reset_btn.setToolTip("Reset and erase saved settings")
        btn_lay2.addWidget(reset_btn)
        layout.addRow(btn_lay2)

        self.setLayout(layout)

        self.transform_combo.setEditText(self.settings["last_transform"])
        self.update_gui()

        self.transform_combo.lineEdit().editingFinished.connect(
            self.on_transform_change
        )
        self.transform_combo.currentIndexChanged.connect(self.on_transform_change)
        dlg_ok.clicked.connect(self.accept)
        dlg_cancel.clicked.connect(self.reject)
        reset_btn.clicked.connect(self.reset_to_defaults)

    def raise_error_msg(self, err, inf_text=None):
        msg = QMessageBox(
            QMessageBox.Critical, "Error", err, QMessageBox.Ok, parent=self
        )
        if inf_text is not None:
            msg.setInformativeText(inf_text)
        msg.exec_()

    def on_transform_change(self):
        """
        Update gui on transform change. Change label and formatting if known
        """
        txt = self.transform_combo.currentText()

        if txt == "":
            return

        trans = get_transform(txt)
        if trans is None:
            self.raise_error_msg(f"The transform '{txt}' is invalid")
            self.transform_combo.setCurrentText(self.settings["last_transform"])
            return

        self.transform_combo.setEditText(trans[0])
        self.settings["last_transform"] = trans[0]
        self.update_gui()

    def get_combo_items(self, combo):
        """
        get combobox items to include text in the lineedit
        """
        items = [combo.currentText()]
        items = items + [combo.itemText(i) for i in range(combo.count())]
        return list(set(items))

    def update_gui(self):
        """
        update the gui based on self.settings
        """
        # try to use last transform settings if known
        trans = self.settings["last_transform"]
        if trans in self.settings["transforms"]:
            self.transform_combo.setCurrentText(trans)
            if "transform_name" in self.settings["transforms"][trans]:
                self.transform_name_edit.setText(
                    self.settings["transforms"][trans]["transform_name"]
                )
            if "x_format" in self.settings["transforms"][trans]:
                self.x_format_combo.setCurrentText(
                    self.settings["transforms"][trans]["x_format"]
                )
            if "y_format" in self.settings["transforms"][trans]:
                self.y_format_combo.setCurrentText(
                    self.settings["transforms"][trans]["y_format"]
                )
            if "scaler" in self.settings["transforms"][trans]:
                self.scaler_combo.setCurrentText(
                    self.settings["transforms"][trans]["scaler"]
                )

        # otherwise guess
        txt = self.transform_name_edit.text()
        if (txt == "") or txt.startswith("EPSG"):
            self.transform_name_edit.setText(trans)
        if self.x_format_combo.currentText() == "":
            self.x_format_combo.setCurrentText(",.0f")
        if self.y_format_combo.currentText() == "":
            self.y_format_combo.setCurrentText(",.0f")
        if self.scaler_combo.currentText() == "":
            self.scaler_combo.setCurrentText("1")

    def update_settings(self):
        """
        update self.settings based on what the gui
        """
        trans = self.transform_combo.currentText()
        trans_label = self.transform_name_edit.text()
        x_format = self.x_format_combo.currentText()
        y_format = self.y_format_combo.currentText()
        scaler = self.scaler_combo.currentText()
        setting = {
            "transform_name": trans_label,
            "x_format": x_format,
            "y_format": y_format,
            "scaler": scaler,
        }

        if trans in self.settings["transforms"]:
            self.settings["transforms"][trans].update(setting)
        else:
            self.settings["transforms"][trans] = setting
        self.settings["last_transform"] = trans

        self.settings["x_formats"] = self.get_combo_items(self.x_format_combo)
        self.settings["y_formats"] = self.get_combo_items(self.y_format_combo)
        self.settings["scalers"] = self.get_combo_items(self.scaler_combo)

        return self.settings

    def accept(self):
        """
        override accept to validate and update settings first
        """
        # just to be safe, recheck the transform
        trans = self.transform_combo.currentText()
        if get_transform(trans) is None:
            self.raise_error_msg(f"The transform '{trans}' is invalid")
            return

        # also check number formatting
        try:
            f"{1.2:{self.x_format_combo.currentText()}}"
        except ValueError:
            self.raise_error_msg("The x format string is invalid")
            return

        try:
            f"{1.2:{self.y_format_combo.currentText()}}"
        except ValueError:
            self.raise_error_msg("The y format string is invalid")
            return

        try:
            int(self.scaler_combo.currentText())
        except ValueError:
            self.raise_error_msg("Multiplier is not an integer")
            return

        self.update_settings()
        super().accept()

    def reset_to_defaults(self):
        self.settings = copy.deepcopy(self.parent().default_settings)

        # reset items in comboboxes
        self.transform_combo.clear()
        self.transform_combo.addItems([k for k in self.settings["transforms"].keys()])
        self.x_format_combo.clear()
        self.x_format_combo.addItems(self.settings["x_formats"])
        self.y_format_combo.clear()
        self.y_format_combo.addItems(self.settings["y_formats"])
        self.scaler_combo.clear()
        self.scaler_combo.addItems(self.settings["scalers"])

        self.update_gui()


class SecondaryCoordinates(QWidget):
    def __init__(self, iface: QgisInterface, parent=None):
        super().__init__(parent)

        self.iface = iface

        QCoreApplication.setOrganizationName("SWFSC")
        QCoreApplication.setOrganizationDomain("swfsc.noaa.gov")
        QCoreApplication.setApplicationName("qgis_secondary_coordinates")

        self.default_settings = {
            "transforms": {
                "EPSG:6414": {
                    "x_format": ",.0f",
                    "y_format": ",.0f",
                    "transform_name": "EPSG:6414",
                    "scaler": "1",
                },
                "+proj=calcofi +ellps=clrk66": {
                    "x_format": ",.1f",
                    "y_format": ",.1f",
                    "transform_name": "Line, Station",
                    "scaler": "1",
                },
            },
            "last_transform": "EPSG:6414",
            "x_formats": [".1f", ",.0f"],
            "y_formats": [".1f", ",.0f"],
            "scalers": ["1", "1000", "1852"],
        }

        self.settings = None
        self.read_settings()

        self.action = None
        self.label = None
        self.edit = None
        self.btn = None

        self.xy = None
        self._transform = "EPSG:6414"
        self._crs = QgsCoordinateTransform(
            QgsProject.instance().crs(),
            QgsCoordinateReferenceSystem(self._transform),
            QgsProject.instance(),
        )

        self._x_format = ",.0f"
        self._y_format = ",.0f"
        self._x_formatter = lambda x: f"{x:,.0f}"
        self._y_formatter = lambda y: f"{y:,.0f}"
        self._scaler = 1
        self._transform_name = "EPSG:6414"

    def _recursive_update(self, d1, d2):
        """
        recursively update dicts for use with settings
        """
        for k, v in d2.items():
            if isinstance(v, dict) and k in d1 and isinstance(d1[k], dict):
                self._recursive_update(d1[k], v)
            else:
                d1[k] = v
        return d1

    def read_settings(self):
        settings = QSettings()
        settings.beginGroup("qgis_secondary_coordinates")
        # remember json will be text for everything
        json_settings = settings.value("settings", "")
        settings.endGroup()

        self.settings = copy.deepcopy(self.default_settings)

        if json_settings:
            json_dict = json.loads(json_settings)
            self.settings = self._recursive_update(self.settings, json_dict)

    def write_settings(self):
        settings = QSettings()
        settings.beginGroup("qgis_secondary_coordinates")
        json_dat = json.dumps(self.settings)
        settings.setValue("settings", json_dat)
        settings.endGroup()

    def initGui(self):
        layout = QHBoxLayout()

        # label
        label_layout = QVBoxLayout()
        label_layout.setAlignment(Qt.AlignVCenter)
        self.label = QLabel(self._transform_name)
        self.label.setToolTip("2nd° coordinate units")
        self.label.setAlignment(Qt.AlignLeft)
        label_layout.addWidget(self.label)
        layout.addLayout(label_layout)

        # lineedit -- use a disabled lineedit to make this look
        # consistent with built-in widgets on the status bar
        self.edit = QLineEdit()
        self.edit.setToolTip("2nd° coordinates")
        self.edit.setReadOnly(True)
        self.edit.setFixedWidth(100)
        layout.addWidget(self.edit)

        # settings icon
        self.btn = QPushButton()
        self.btn.setIcon(
            QIcon(
                self.iface.mainWindow()
                .style()
                .standardIcon(QStyle.SP_FileDialogDetailedView)
            )
        )
        self.btn.setToolTip("Configure 2nd° coordinates")
        self.btn.clicked.connect(self.on_config_dialog)
        layout.addWidget(self.btn)

        self.setLayout(layout)
        self.iface.mainWindow().statusBar().addWidget(self)

        # use the font the status bar is already using
        font = self.iface.mainWindow().statusBar().font()
        self.label.setFont(font)
        self.edit.setFont(font)

        self.update_from_settings()
        canvas = self.iface.mapCanvas()
        canvas.xyCoordinates.connect(self.read_coords)

        # update the source crs when a project is
        # opened or at startup (when it is None).
        self.iface.projectRead.connect(self.update_src_crs)

    def unload(self):
        self.iface.mainWindow().statusBar().removeWidget(self)

    def update_src_crs(self):
        src_crs = QgsProject.instance().crs()
        if self._crs.sourceCrs() != src_crs:
            self._crs.setSourceCrs(src_crs)

    def update_from_settings(self, settings=None):
        """
        update object transform, label and units from settings.
        Default is self.settings. If settings are provided, it
        will also update self.settings to match.
        """
        if settings is None:
            settings = self.settings

        trans = settings["last_transform"]
        self.transform = trans
        self.transform_name = settings["transforms"][trans]["transform_name"]
        self.x_format = settings["transforms"][trans]["x_format"]
        self.y_format = settings["transforms"][trans]["y_format"]
        self.scaler = int(settings["transforms"][trans]["scaler"])
        self.settings = settings
        self.write_settings()

        self.edit.setText("")

    def on_config_dialog(self):
        dlg = ConfigDialog(self)
        res = dlg.exec_()
        if res == dlg.Accepted:
            self.update_from_settings(dlg.settings)

    def read_coords(self, xy):
        """
        this is the method that actually reads and prints the coordinates
        xy is a QgsPointXY instance

        """
        self.xy = xy

        # in case a crs change was missed
        self.update_src_crs()

        try:
            x, y = self._crs.transform(self.xy)
        except QgsCsException:
            self.edit.setText("")
            return

        x = x / self.scaler
        y = y / self.scaler
        self.edit.setText(self._x_formatter(x) + ", " + self._y_formatter(y))

    @property
    def x_format(self):
        return self._x_format

    @x_format.setter
    def x_format(self, value):
        """
        set x and y formatting using standard python number
        formatting, e.g., ".1f" ",.0f"
        """
        self._x_format = value
        self._x_formatter = lambda x: f"{x:{self._x_format}}"

    @property
    def y_format(self):
        return self._y_format

    @y_format.setter
    def y_format(self, value):
        """
        set x and y formatting using standard python number
        formatting, e.g., ".1f" ",.0f"
        """
        self._y_format = value
        self._y_formatter = lambda y: f"{y:{self._y_format}}"

    @property
    def scaler(self):
        return self._scaler

    @scaler.setter
    def scaler(self, value):
        """
        quick and dirty conversion, e.g., divide coords
        by 1,000 to convert m -> km
        """
        self._scaler = int(value)

    @property
    def transform_name(self):
        return self.label.text()

    @transform_name.setter
    def transform_name(self, value):
        self.label.setText(value)
        self._label_text = value

    @property
    def transform(self):
        return self._transform

    @transform.setter
    def transform(self, value):
        """
        transform is an epsg code as an integer or string, or a well-known text string,
        e.g., any of the following will work

        transform = 6414
        transform = "EPSG:6414"
        transform = 'PROJCS["NAD83(2011) / California Albers",GEOGCS["NAD83(2011)",DATUM["NAD83_National_Spatial_Reference_System_2011",SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],AUTHORITY["EPSG","1116"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","6318"]],PROJECTION["Albers_Conic_Equal_Area"],PARAMETER["latitude_of_center",0],PARAMETER["longitude_of_center",-120],PARAMETER["standard_parallel_1",34],PARAMETER["standard_parallel_2",40.5],PARAMETER["false_easting",0],PARAMETER["false_northing",-4000000],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH],AUTHORITY["EPSG","6414"]]'
        """
        trans = get_transform(value)
        if trans is None:
            raise ValueError(f"The transform '{value}' is invalid")

        self._transform, self._crs = trans


def run(self):
    dialog = SecondaryCoordinates()
    if dialog.exec_():
        pass
