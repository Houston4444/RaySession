
# Imports from standard library
from enum import IntEnum
from typing import Optional

# third party imports
from qtpy.QtCore import Qt, QDateTime, QDate
from qtpy.QtWidgets import QDialogButtonBox, QTreeWidgetItem

# imports from shared
import osc_paths.ray as r

# Local imports
from child_dialogs import ChildDialog
from gui_tools import _translate, RS

# Import UIs made with Qt-Designer
import ui.snapshot_name
import ui.list_snapshots
import ui.snapshots_info


class InvalidSnapshot(Exception):
    def __init__(
            self, 
            message='Can not access to this func for an invalid snapshot'):
        super().__init__(message)


class SnGroup(IntEnum):
    ELEMENT = 0
    DAY = 1
    MONTH = 2
    YEAR = 3
    MAIN = 4


class Snapshot:
    valid = False
    text = ''
    sub_type = SnGroup.ELEMENT
    item = None
    before_rewind_to = ''
    rewind_date_time: Optional[QDateTime] = None
    session_name = ""
    label = ''
    rewind_label = ''
    ref = ''

    def __init__(self, date_time: Optional[QDateTime]):
        self.date_time = date_time

    def __lt__(self, other: 'Snapshot'):
        if not other.is_valid():
            return True

        if not self.is_valid():
            return False
        
        if self.date_time is None:
            return False
        if other.date_time is None:
            return True

        return self.date_time < other.date_time

    @staticmethod
    def new_from_snaptext(snaptext: str) -> 'Snapshot':
        time_str_full, line_change, rw_time_str_full_sess = \
            snaptext.partition('\n')
        rw_time_str_full, line_change, session_name = \
            rw_time_str_full_sess.partition('\n')

        time_str, two_points, label = time_str_full.partition(':')
        rw_time_str, two_points, rw_label = rw_time_str_full.partition(':')

        utc_date_time = QDateTime.fromString(time_str, 'yyyy_M_d_h_m_s')
        utc_rw_date_time = QDateTime.fromString(rw_time_str,
                                                'yyyy_M_d_h_m_s')
        utc_date_time.setTimeSpec(Qt.TimeSpec.OffsetFromUTC)
        utc_rw_date_time.setTimeSpec(Qt.TimeSpec.OffsetFromUTC)

        date_time = None
        rw_date_time = None

        if utc_date_time.isValid():
            date_time = utc_date_time.toLocalTime()

        if utc_rw_date_time.isValid():
            rw_date_time = utc_rw_date_time.toLocalTime()

        snapshot = Snapshot(date_time)
        snapshot.text = snaptext
        snapshot.label = label
        snapshot.rewind_date_time = rw_date_time
        snapshot.rewind_label = rw_label
        snapshot.session_name = session_name
        return snapshot

    def year(self) -> int:
        if self.date_time is None:
            raise InvalidSnapshot
        return self.date_time.date().year()

    def month(self) -> int:
        if self.date_time is None:
            raise InvalidSnapshot
        return self.date_time.date().month()

    def day(self) -> int:
        if self.date_time is None:
            raise InvalidSnapshot
        return self.date_time.date().day()

    def is_valid(self) -> bool:
        if self.date_time is None:
            return False

        return self.date_time.isValid()

    def is_today(self) -> bool:
        if not self.date_time:
            return False

        return bool(self.date_time.date() == QDate.currentDate())

    def is_yesterday(self) -> bool:
        if not self.date_time:
            return False

        return bool(self.date_time.date() == QDate.currentDate().addDays(-1))

    def can_take(self, other) -> bool:
        return False

    def sort(self):...
    def add(self, other):...

    def common_group(self, other: 'Snapshot') -> SnGroup:
        if not (self.is_valid() and other.is_valid()):
            return SnGroup.MAIN

        common_group = SnGroup.MAIN

        if self.year() == other.year():
            common_group = SnGroup.YEAR
            if self.month() == other.month():
                common_group = SnGroup.MONTH
                if self.day() == other.day():
                    common_group = SnGroup.DAY

        if common_group <= self.sub_type:
            return SnGroup(self.sub_type + 1)

        return common_group

    def make_item(self, sub_type):
        if self.date_time is None:
            display_text = self.text
        else:
            if self.is_today():
                day_string = _translate('snapshots', 'Today')
            elif self.is_yesterday():
                day_string = _translate('snapshots', 'Yesterday')
            else:
                day_string = self.date_time.toString('dddd d MMMM yyyy')
            
            display_text = _translate('snapshots', "%s at %s") % (
                                day_string, self.date_time.toString('HH:mm'))

            if sub_type in (SnGroup.YEAR, SnGroup.MONTH):
                if not self.is_today() or self.is_yesterday():
                    day_string = self.date_time.toString('dddd d MMMM')

                display_text = _translate('snapshots', "%s at %s") % (
                                    day_string,
                                    self.date_time.toString('HH:mm'))

            elif sub_type is SnGroup.DAY:
                display_text = _translate('snapshots', "at %s") \
                                 % self.date_time.toString('HH:mm')

            if self.rewind_date_time:
                display_text += '\n'
                display_text += _translate('snapshots', "before rewind to ")

                if self.rewind_label:
                    display_text += self.rewind_label
                elif self.rewind_date_time.date() == self.date_time.date():
                    display_text += self.rewind_date_time.toString('hh:mm')
                elif (self.rewind_date_time.date().year()
                    == self.date_time.date().year()):
                    display_text += self.rewind_date_time.toString('d MMM hh:mm')
                else:
                    display_text += self.rewind_date_time.toString('d MMM yyyy hh:mm')

            elif self.session_name:
                display_text += "\nsession name: %s" % self.session_name

        if self.label:
            display_text += "\n%s" % self.label

        item = QTreeWidgetItem([display_text])
        item.setData(0, Qt.ItemDataRole.UserRole, self.text)

        return item


class SnapGroup(Snapshot):
    def __init__(self, date_time=None, sub_type=SnGroup.MAIN):
        Snapshot.__init__(self, date_time)
        self.sub_type = sub_type
        self.valid = True
        self.snapshots = list[Snapshot]()

    def can_take(self, other: 'Snapshot'):
        if self.sub_type <= other.sub_type:
            return False

        if self.sub_type is SnGroup.MAIN:
            return True

        if self.year() != other.year():
            return False

        if self.sub_type is SnGroup.YEAR:
            return True

        if self.month() != other.month():
            return False

        if self.sub_type is SnGroup.MONTH:
            return True

        if self.day() != other.day():
            return False

        return True

    def add(self, new_snapshot: 'Snapshot'):
        if not new_snapshot.is_valid():
            self.snapshots.append(new_snapshot)
            return

        if self.sub_type in (SnGroup.ELEMENT, SnGroup.DAY):
            # If this group (self) is a day group, just add this snapshot
            self.snapshots.append(new_snapshot)
            return

        for snapshot in self.snapshots:
            if snapshot.can_take(new_snapshot):
                # if a snapgroup can take this snapshot,
                # just add this snapshot to this snapgroup.
                snapshot.add(new_snapshot)
                return

        smallest_cg = self.sub_type

        # find the smallest common group with any other
        for snapshot in self.snapshots:
            common_group = snapshot.common_group(new_snapshot)
            if common_group < smallest_cg:
                smallest_cg = common_group

        # check if there are snaps not common
        # with the smallest common group find above (smallest_cg)
        for snapshot in self.snapshots:
            common_group = snapshot.common_group(new_snapshot)
            if common_group != smallest_cg:
                break
        else:
            # There is no snap outside of smallest_cg
            # but there are maybe others snapshots to group together
            cg_final = 0
            compare_snap = Snapshot(None)

            for cg in (SnGroup.DAY, SnGroup.MONTH, SnGroup.YEAR):
                if cg_final:
                    break

                if cg >= smallest_cg:
                    continue

                # compare all existing snapshots with all others
                for i in range(len(self.snapshots)):
                    if cg_final:
                        break

                    compare_snap = self.snapshots[i]
                    if compare_snap.sub_type >= cg:
                        continue

                    for j in range(len(self.snapshots)):
                        if j <= i:
                            # prevent compare to itself or already compared
                            continue

                        snapshot = self.snapshots[j]
                        if snapshot.sub_type >= cg:
                            continue

                        if (snapshot.common_group(compare_snap) == cg
                                and snapshot.common_group(new_snapshot) > cg):
                            cg_final = cg
                            break

            if cg_final:
                snap_group = SnapGroup(compare_snap.date_time, cg_final)
                self.add_group(snap_group)

            self.snapshots.append(new_snapshot)
            return

        # create group and add to this all snaps which have to.
        snap_group = SnapGroup(new_snapshot.date_time, smallest_cg)
        snap_group.add(new_snapshot)
        self.add_group(snap_group)

    def add_group(self, snap_group: 'SnapGroup'):
        to_rem = list[int]()

        for i in range(len(self.snapshots)):
            snapshot = self.snapshots[i]
            if snap_group.can_take(snapshot):
                snap_group.add(snapshot)
                to_rem.append(i)

        to_rem.reverse()
        for i in to_rem:
            self.snapshots.__delitem__(i)

        self.snapshots.append(snap_group)

    def sort(self):
        for snapshot in self.snapshots:
            snapshot.sort()

        self.snapshots.sort()
        self.snapshots.reverse()

    def make_item(self, sub_type=SnGroup.MAIN):
        display_text = ''

        if self.sub_type is SnGroup.MAIN:
            return None

        if not self.date_time:
            display_text = self.text
        elif self.sub_type is SnGroup.YEAR:
            display_text = self.date_time.toString('yyyy')
        elif self.sub_type is SnGroup.MONTH:
            display_text = self.date_time.toString('MMMM yyyy')
        elif self.sub_type is SnGroup.DAY:
            display_text = self.date_time.toString('dddd d MMMM yyyy')
            if self.is_today():
                display_text = _translate('snapshots', 'Today')
            elif self.is_yesterday():
                display_text = _translate('snapshots', 'Yesterday')

        item = QTreeWidgetItem([display_text])

        for snapshot in self.snapshots:
            sub_item = snapshot.make_item(self.sub_type)
            item.addChild(sub_item)

        # set this group item not selectable
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

        return item


class TakeSnapshotDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.snapshot_name.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.lineEdit.textChanged.connect(self._text_changed)
        self.ui.pushButtonSave.setEnabled(False)
        self.ui.pushButtonSnapshot.setEnabled(False)

        self._save_asked = False
        self.ui.pushButtonSave.clicked.connect(self._accept_with_save)

    def _text_changed(self, text):
        self.ui.pushButtonSave.setEnabled(bool(text))
        self.ui.pushButtonSnapshot.setEnabled(bool(text))

    def _accept_with_save(self):
        self._save_asked = True
        self.accept()

    def get_snapshot_name(self):
        return self.ui.lineEdit.text()

    def save_asked(self):
        return self._save_asked


class SnapshotsDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.list_snapshots.Ui_Dialog()
        self.ui.setupUi(self)

        self._original_label = self.ui.label.text()
        self.signaler.reply_auto_snapshot.connect(
            self.ui.checkBoxAutoSnapshot.setChecked)
        self.signaler.snapshots_found.connect(self._add_snapshots)

        self.snapshots = []
        self.main_snap_group = SnapGroup()

        self.ui.snapshotsList.setHeaderHidden(True)
        self.ui.snapshotsList.currentItemChanged.connect(
            self._current_item_changed)

        self.ui.buttonBox.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(False) # type:ignore

    def _current_item_changed(self, current, previous):
        self.ui.buttonBox.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled( # type:ignore
                bool(current and current.data(0, Qt.ItemDataRole.UserRole)))

    def _add_snapshots(self, snaptexts):
        if not snaptexts and not self.main_snap_group.snapshots:
            # Snapshot list finished without any snapshot
            self._no_snapshot_found()
            return

        for snaptext in snaptexts:
            if not snaptext:
                continue

            snapshot = Snapshot.new_from_snaptext(snaptext)
            self.main_snap_group.add(snapshot)

        self.main_snap_group.sort()

        self.ui.snapshotsList.clear()

        for snapshot in self.main_snap_group.snapshots:
            item = snapshot.make_item(SnGroup.MAIN)
            self.ui.snapshotsList.addTopLevelItem(item)

        self.ui.buttonBox.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(False) # type:ignore
        self.ui.snapshotsList.clearSelection()

    def _no_snapshot_found(self):
        pass

    def get_selected_snapshot(self) -> Optional[str]:
        item = self.ui.snapshotsList.currentItem()
        if item is None:
            return None
        full_str: str = item.data(0, Qt.ItemDataRole.UserRole)
        snapshot_ref = full_str.partition('\n')[0].partition(':')[0]

        return snapshot_ref

    def showEvent(self, event):
        ChildDialog.showEvent(self, event)

        if RS.is_hidden(RS.HD_SnapshotsInfo):
            return

        info_dialog = SnapshotsInfoDialog(self)
        info_dialog.exec()

        if info_dialog.has_to_be_hidden_next_time():
            RS.set_hidden(RS.HD_SnapshotsInfo)


class SnapshotsInfoDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.snapshots_info.Ui_Dialog()
        self.ui.setupUi(self)

    def has_to_be_hidden_next_time(self):
        return self.ui.checkBox.isChecked()


class SessionSnapshotsDialog(SnapshotsDialog):
    def __init__(self, parent):
        SnapshotsDialog.__init__(self, parent)

        self.ui.pushButtonSnapshotNow.clicked.connect(self._take_snapshot)

        self.to_daemon(r.session.LIST_SNAPSHOTS)

        self.ui.checkBoxAutoSnapshot.stateChanged.connect(
            self._set_auto_snapshot)

    def _take_snapshot(self):
        dialog = TakeSnapshotDialog(self)
        dialog.exec()
        if dialog.result():
            snapshot_label = dialog.get_snapshot_name()
            with_save = dialog.save_asked()
            self.to_daemon(r.session.TAKE_SNAPSHOT, snapshot_label,
                          int(with_save))
            self.ui.snapshotsList.setVisible(True)
            self.ui.label.setText(self._original_label)

    def _set_auto_snapshot(self, bool_snapshot):
        self.to_daemon(r.session.SET_AUTO_SNAPSHOT, int(bool_snapshot))

    def _no_snapshot_found(self):
        self.ui.label.setText(
            _translate('snapshots',
                       "This session does not contains any snapshot."))
        self.ui.snapshotsList.setVisible(False)


class ClientSnapshotsDialog(SnapshotsDialog):
    def __init__(self, parent, client):
        SnapshotsDialog.__init__(self, parent)
        self.ui.pushButtonSnapshotNow.hide()
        self.ui.checkBoxAutoSnapshot.hide()

        self.client = client

        self.to_daemon(r.client.LIST_SNAPSHOTS, client.client_id)
        self.resize(0, 0)

    def _no_snapshot_found(self):
        self.ui.label.setText(
            _translate('snapshots',
                       'There is no existing snapshot for this client.'))
        self.ui.snapshotsList.setVisible(False)
