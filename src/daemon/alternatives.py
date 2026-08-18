from typing import TYPE_CHECKING

import osc_paths.ray.gui as rg

if TYPE_CHECKING:
    from session import Session
    

def send_gui(session: 'Session'):
    '''Send all alternatives to GUI(s)'''
    out_list = list[str]()
    for alter_group in session.alternative_groups:
        out_list += list(alter_group) + ['']
    session.send_gui(rg.session.ALTERNATIVE_GROUPS, *out_list)

def add_alternative(session: 'Session', client_id: str, alt_client_id: str):
    '''Add `alt_client_id` alternative to `client_id`.

    `client_id` must be in `session.clients`,
    `alt_client_id` must be in `session.trashed_clients`,
    no check is operated.'''
    has_id_1, has_id_2, together = False, False, False
    for alter_group in session.alternative_groups:
        if client_id in alter_group:
            has_id_1 = True
            if alt_client_id in alter_group:
                has_id_1, has_id_2, together = True, True, True
                break
        elif alt_client_id in alter_group:
            has_id_2 = True
            
    if together:
        pass

    elif has_id_1 and has_id_2:
        for alter_group in session.alternative_groups:
            alter_group.discard(client_id)
            alter_group.discard(alt_client_id)
    
        for alter_group in session.alternative_groups.copy():
            if len(alter_group) < 2:
                session.alternative_groups.remove(alter_group)
    
        session.alternative_groups.append({client_id, alt_client_id})
        
    elif has_id_1:
        for alter_group in session.alternative_groups:
            if client_id in alter_group:
                alter_group.add(alt_client_id)
                break
    
    elif has_id_2:
        for alter_group in session.alternative_groups:
            if client_id in alter_group:
                alter_group.add(alt_client_id)
                break
    else:
        session.alternative_groups.append({client_id, alt_client_id})
        
    send_gui(session)
    
def remove_alternative(session: 'Session', alt_client_id: str):
    '''remove `alt_client_id` from alternatives, no matter to which client_id
    it was affected.'''
    for alter_group in session.alternative_groups.copy():
        alter_group.discard(alt_client_id)
        if len(alter_group) < 2:
            session.alternative_groups.remove(alter_group)
            
    send_gui(session)