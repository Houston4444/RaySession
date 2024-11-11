import os
import shutil

def which_terminal(title='', hold=True) -> list[str]:
        """ returns the most appropriate terminal executable
            with its arguments """
        terminals = ['gnome-terminal', 'mate-terminal', 'xfce4-terminal',
                     'xterm', 'konsole', 'lxterminal', 'rxvt']
        current_desktop = os.getenv('XDG_CURRENT_DESKTOP')
        terminal = ''

        # make prior most appropriate terminal
        if current_desktop == 'GNOME':
            pass

        elif current_desktop == 'KDE':
            terminals.remove('konsole')
            terminals.insert(0, 'konsole')

        elif current_desktop == 'MATE':
            terminals.remove('mate-terminal')
            terminals.insert(0, 'mate-terminal')

        elif current_desktop == 'XFCE':
            terminals.remove('xfce4-terminal')
            terminals.insert(0, 'xfce4-terminal')
            terminals.insert(0, 'xfce-terminal')

        elif current_desktop == 'LXDE':
            terminals.remove('lxterminal')
            terminals.insert(0, 'lxterminal')

        # search executable for terminals
        for term in terminals:
            if shutil.which(term):
                terminal = term
                break
        else:
            return list[str]()

        if terminal == 'gnome-terminal':
            return [terminal, '--hide-menubar', '--wait', '--']

        if terminal == 'konsole':
            base_args = [terminal, '--hide-tabbar', '--hide-menubar']
            if hold:
                base_args.append('--hold')
            
            if title:
                base_args += ['-p', "tabtitle=%s" % title]
            
            base_args.append('-e')
            
            return base_args

        if terminal == 'mate-terminal':
            if title:
                return [terminal, '--hide-menubar', '--disable-factory',
                        '--title', title, '--']

            return [terminal, '--hide-menubar', '--disable-factory', '--']

        if terminal == 'xfce4-terminal':
            if title:
                return [terminal, '--hide-menubar', '--hide-toolbar',
                        '-T', title, '-e']

            return [terminal, '--hide-menubar', '--hide-toolbar', '-e']

        return [terminal, '-e']