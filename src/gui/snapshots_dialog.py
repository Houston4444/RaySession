from PyQt5.QtCore import Qt, QDateTime, QDate, QTime
from PyQt5.QtWidgets import QDialogButtonBox, QTreeWidgetItem

import ray

from child_dialogs import ChildDialog
from gui_tools import _translate, RS

import ui_list_snapshots
import ui_snapshot_name
import ui_snapshots_info

GROUP_ELEMENT = 0
GROUP_DAY     = 1
GROUP_MONTH   = 2
GROUP_YEAR    = 3
GROUP_MAIN    = 4

class Snapshot:
    valid = False
    text  = ''
    sub_type = GROUP_ELEMENT
    item = None
    before_rewind_to = ''
    date_time = None
    rewind_date_time = None
    session_name = ""
    label = ''
    rewind_label = ''
    ref = ''
    
    def __init__(self, date_time):
        self.date_time = date_time
    
    def __lt__(self, other):
        if not other.isValid():
            return True
        
        if not self.isValid():
            return False
        
        return self.date_time < other.date_time
    
    def year(self):
        return self.date_time.date().year()
    
    def month(self):
        return self.date_time.date().month()
    
    def day(self):
        return self.date_time.date().day()
    
    def isValid(self):
        if not self.date_time:
            return False
        
        return self.date_time.isValid()
    
    def isToday(self):
        if not self.date_time:
            return False
        
        return bool(self.date_time.date() == QDate.currentDate())
    
    def isYesterday(self):
        if not self.date_time:
            return False
        
        return bool(self.date_time.date() == QDate.currentDate().addDays(-1))
    
    def canTake(self, other):
        return False
    
    def reOrganize(self):
        pass
    
    def add(self):
        pass
    
    def commonGroup(self, other):
        if not (self.isValid() and other.isValid()):
            return GROUP_MAIN
        
        common_group = GROUP_MAIN
        
        if self.year() == other.year():
            common_group = GROUP_YEAR
            if self.month() == other.month():
                common_group = GROUP_MONTH
                if self.day() == other.day():
                    common_group = GROUP_DAY
        
        if common_group <= self.sub_type:
            return self.sub_type +1
        
        return common_group
    
    
    
    def makeItem(self, sub_type):
        if self.isToday():
            day_string = _translate('snapshots', 'Today')
        elif self.isYesterday():
            day_string = _translate('snapshots', 'Yesterday')
        elif self.isValid():
            day_string = self.date_time.toString('dddd d MMMM yyyy')
        
        
        if not self.isValid():
            display_text = self.text
        else:
            display_text = _translate('snapshots', "%s at %s") % (
                            day_string,
                            self.date_time.toString('HH:mm'))
            
            if sub_type in (GROUP_YEAR, GROUP_MONTH):
                if not self.isToday() or self.isYesterday():
                    day_string = self.date_time.toString('dddd d MMMM')
                    
                display_text = _translate('snapshots', "%s at %s") % (
                                    day_string,
                                    self.date_time.toString('HH:mm'))
                
            elif sub_type == GROUP_DAY:
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
        item.setData(0, Qt.UserRole, self.text)
        
        return item


class SnapGroup(Snapshot):
    def __init__(self, date_time=None, sub_type=GROUP_MAIN):
        Snapshot.__init__(self, date_time)
        self.sub_type = sub_type
        self.valid = True
        self.snapshots = []
    
    def canTake(self, other):
        if self.sub_type <= other.sub_type:
            return False
        
        if self.sub_type == GROUP_MAIN:
            return True
        
        if self.year() != other.year():
            return False
        
        if self.sub_type == GROUP_YEAR:
            return True
        
        if self.month() != other.month():
            return False
        
        if self.sub_type == GROUP_MONTH:
            return True
        
        if self.day() != other.day():
            return False
        
        return True
    
    def add(self, new_snapshot):
        if not new_snapshot.isValid():
            self.snapshots.append(new_snapshot)
            return
        
        if self.sub_type <= 1:
            # If this group (self) is a day group, just add this snapshot
            self.snapshots.append(new_snapshot)
            return
        
        for snapshot in self.snapshots:
            if snapshot.canTake(new_snapshot):
                # if a snapgroup can take this snapshot,
                # just add this snapshot to this snapgroup.
                snapshot.add(new_snapshot)
                return
        
        smallest_cg = self.sub_type
        
        # find the smallest common group with any other 
        for snapshot in self.snapshots:
            common_group = snapshot.commonGroup(new_snapshot)
            if common_group < smallest_cg:
                smallest_cg = common_group
        
        # check if there are snaps not common
        # with the smallest common group find above (smallest_cg)
        for snapshot in self.snapshots:
            common_group = snapshot.commonGroup(new_snapshot)
            if common_group != smallest_cg:
                break
        else:
            # There is no snap outside of smallest_cg
            # but there are maybe others snapshots to group together
            cg_final = 0
            compare_snap = Snapshot(None)
            
            for cg in (GROUP_DAY, GROUP_MONTH, GROUP_YEAR):
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
                        
                        if (snapshot.commonGroup(compare_snap) == cg
                                and snapshot.commonGroup(new_snapshot) > cg):
                            cg_final = cg
                            break
            
            if cg_final:
                snap_group = SnapGroup(compare_snap.date_time, cg_final)
                self.addGroup(snap_group)
                
            self.snapshots.append(new_snapshot)
            return
        
        # create group and add to this all snaps which have to.
        snap_group = SnapGroup(new_snapshot.date_time, smallest_cg)
        snap_group.add(new_snapshot)
        self.addGroup(snap_group)
    
    def addGroup(self, snap_group):
        to_rem = []
        
        for i in range(len(self.snapshots)):
            snapshot = self.snapshots[i]
            if snap_group.canTake(snapshot):
                snap_group.add(snapshot)
                to_rem.append(i)
                
        to_rem.reverse()
        for i in to_rem:
            self.snapshots.__delitem__(i)
        
        self.snapshots.append(snap_group)
    
    def sort(self):
        for snapshot in self.snapshots:
            if snapshot.sub_type:
                snapshot.sort()
                
        self.snapshots.sort()
        self.snapshots.reverse()
                    
    def makeItem(self, sub_type=GROUP_MAIN):
        display_text = ''
        
        if self.sub_type == GROUP_MAIN:
            return None
        
        if not self.date_time:
            display_text = self.text
        elif self.sub_type == GROUP_YEAR:
            display_text = self.date_time.toString('yyyy')
        elif self.sub_type == GROUP_MONTH:
            display_text = self.date_time.toString('MMMM yyyy')
        elif self.sub_type == GROUP_DAY:
            display_text = self.date_time.toString('dddd d MMMM yyyy')
            if self.isToday():
                display_text = _translate('snapshots', 'Today')
            elif self.isYesterday():
                display_text = _translate('snapshots', 'Yesterday')
            
        item = QTreeWidgetItem([display_text])
        
        for snapshot in self.snapshots:
            sub_item = snapshot.makeItem(self.sub_type)
            item.addChild(sub_item)
        
        # set this group item not selectable
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        
        return item

class TakeSnapshotDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_snapshot_name.Ui_Dialog()
        self.ui.setupUi(self)
        
        self.ui.lineEdit.textChanged.connect(self.textChanged)
        #self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.pushButtonSave.setEnabled(False)
        self.ui.pushButtonSnapshot.setEnabled(False)
        
        self.__save_asked = False
        self.ui.pushButtonSave.clicked.connect(self.acceptWithSave)
        
    def textChanged(self, text):
        #self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(bool(text))
        self.ui.pushButtonSave.setEnabled(bool(text))
        self.ui.pushButtonSnapshot.setEnabled(bool(text))
        
    def getSnapshotName(self):
        return self.ui.lineEdit.text()
    
    def saveAsked(self):
        return self.__save_asked
    
    def acceptWithSave(self):
        self.__save_asked = True
        self.accept()
    
    
class SnapshotsDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_list_snapshots.Ui_Dialog()
        self.ui.setupUi(self)
        
        self._signaler.reply_auto_snapshot.connect(self.ui.checkBoxAutoSnapshot.setChecked)
        self._signaler.snapshots_found.connect(self.addSnapshots)
        
        self.snapshots = []
        self.main_snap_group = SnapGroup()
        
        self.ui.snapshotsList.setHeaderHidden(True)
        #self.ui.snapshotsList.setRootIsDecorated(False)
        self.ui.snapshotsList.currentItemChanged.connect(
            self.currentItemChanged)
        
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
    
    def currentItemChanged(self, current, previous):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
           bool(current and current.data(0, Qt.UserRole))) 
    
    def decodeTimeString(self, time_str):
        while time_str.endswith('_'):
            time_str = time_str[:-1]
        
        label = ''
        strs = time_str.split('_')
        
        if len(strs) > 6:
            time_str = ''
            i = 0
            for stri in strs:
                if i < 6: 
                    time_str += "%s_" % stri
                else:
                    label += "%s_" % stri
                i+=1
                
            time_str = time_str[:-1]
            label = label[:-1]
            
        return (time_str, label)
    
    def addSnapshots(self, snaptexts):
        for snaptext in snaptexts:
            if not snaptext:
                continue
            
            time_str_full, line_change, rw_time_str_full_sess = \
                snaptext.partition('\n')
            rw_time_str_full, line_change, session_name = \
                rw_time_str_full_sess.partition('\n')
            
            time_str, two_points, label = time_str_full.partition(':')
            rw_time_str, two_points, rw_label = rw_time_str_full.partition(':')
            
            utc_date_time = QDateTime.fromString(time_str, 'yyyy_M_d_h_m_s')
            utc_rw_date_time = QDateTime.fromString(rw_time_str,
                                                'yyyy_M_d_h_m_s')
            utc_date_time.setTimeSpec(Qt.OffsetFromUTC)
            utc_rw_date_time.setTimeSpec(Qt.OffsetFromUTC)
            
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
            
            self.main_snap_group.add(snapshot)
            
        self.main_snap_group.sort()
        
        self.ui.snapshotsList.clear()
        
        for snapshot in self.main_snap_group.snapshots:
            item = snapshot.makeItem(GROUP_MAIN)
            self.ui.snapshotsList.addTopLevelItem(item)
            
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.snapshotsList.clearSelection()
    
    def getSelectedSnapshot(self):
        item = self.ui.snapshotsList.currentItem()
        full_str = item.data(0, Qt.UserRole)
        snapshot_ref = full_str.partition('\n')[0].partition(':')[0]
        
        return snapshot_ref
    
    def showEvent(self, event):
        ChildDialog.showEvent(self, event)
        
        if RS.settings.value('hide_snapshots_info'):
            return
        
        info_dialog = SnapshotsInfoDialog(self)
        info_dialog.exec()
        
        if info_dialog.hasToBeHiddenNextTime():
            RS.settings.setValue('hide_snapshots_info', True)
        
    
class SnapshotsInfoDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_snapshots_info.Ui_Dialog()
        self.ui.setupUi(self)
    
    def hasToBeHiddenNextTime(self):
        return self.ui.checkBox.isChecked()

class SessionSnapshotsDialog(SnapshotsDialog):
    def __init__(self, parent):
        SnapshotsDialog.__init__(self, parent)
        
        self.ui.pushButtonSnapshotNow.clicked.connect(self.takeSnapshot)
        
        self.toDaemon('/ray/session/ask_auto_snapshot')
        self.toDaemon('/ray/session/list_snapshots')
        
        self.ui.checkBoxAutoSnapshot.stateChanged.connect(self.setAutoSnapshot)
        
    def takeSnapshot(self):
        dialog = TakeSnapshotDialog(self)
        dialog.exec()
        if dialog.result():
            snapshot_label = dialog.getSnapshotName()
            with_save = dialog.saveAsked()
            self.toDaemon('/ray/session/take_snapshot', snapshot_label,
                          int(with_save))
    
    def setAutoSnapshot(self, bool_snapshot):
        self.toDaemon('/ray/session/set_auto_snapshot', int(bool_snapshot))

class ClientSnapshotsDialog(SnapshotsDialog):
    def __init__(self, parent, client):
        SnapshotsDialog.__init__(self, parent)
        self.ui.pushButtonSnapshotNow.hide()
        self.ui.checkBoxAutoSnapshot.hide()
        
        self.client = client
        
        self.toDaemon('/ray/client/list_snapshots', client.client_id)
        
