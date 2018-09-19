from os.path import join
from xlrd import open_workbook
from xlrd.biffh import XLRDError

from eNMS import db
from eNMS.admin.models import Parameters, User
from eNMS.base.custom_base import factory
from eNMS.base.helpers import integrity_rollback, retrieve
from eNMS.objects.models import Device, Pool
from eNMS.objects.routes import process_kwargs
from eNMS.services.models import (
    NapalmConfigService,
    NapalmGettersService,
    RestCallService,
    Service
)
from eNMS.services.custom_service import service_classes
from eNMS.tasks.models import ServiceTask, Task, WorkflowTask
from eNMS.workflows.models import Workflow, WorkflowEdge


def create_default_user():
    factory(User, **{
        'name': 'cisco',
        'email': 'cisco@cisco.com',
        'password': 'cisco'
    })


def create_default_pools():
    for pool in (
        {'name': 'All objects'},
        {'name': 'Devices only', 'link_name': '^$', 'link_name_regex': True},
        {'name': 'Links only', 'device_name': '^$', 'device_name_regex': True}
    ):
        factory(Pool, **pool)


@integrity_rollback
def create_default_parameters():
    parameters = Parameters()
    db.session.add(parameters)
    db.session.commit()


@integrity_rollback
def create_default_network_topology(app):
    with open(join(app.path, 'projects', 'defaults.xls'), 'rb') as f:
        book = open_workbook(file_contents=f.read())
        for object_type in ('Device', 'Link'):
            try:
                sheet = book.sheet_by_name(object_type)
            except XLRDError:
                continue
            properties = sheet.row_values(0)
            for row_index in range(1, sheet.nrows):
                values = dict(zip(properties, sheet.row_values(row_index)))
                cls, kwargs = process_kwargs(app, **values)
                factory(cls, **kwargs).serialized
            db.session.commit()


def create_netmiko_services():
    for service in (
        {
            'type': service_classes['Netmiko Configuration Service'],
            'name': 'netmiko_create_vrf_TEST',
            'description': 'Create a VRF "TEST" with Netmiko',
            'vendor': 'Cisco',
            'operating_system': 'IOS',
            'content_type': 'simple',
            'driver': 'cisco_ios',
            'global_delay_factor': '1.0',
            'content': 'ip vrf TEST'
        },
        {
            'type': service_classes['Netmiko Validation Service'],
            'name': 'netmiko_check_vrf_TEST',
            'description': 'Check that the vrf "TEST" is configured',
            'vendor': 'Cisco',
            'operating_system': 'IOS',
            'driver': 'cisco_ios',
            'command1': 'show ip vrf',
            'content_match1': 'TEST'
        },
        {
            'type': service_classes['Netmiko Configuration Service'],
            'name': 'netmiko_delete_vrf_TEST',
            'description': 'Delete VRF "TEST"',
            'vendor': 'Cisco',
            'operating_system': 'IOS',
            'content_type': 'simple',
            'driver': 'cisco_ios',
            'global_delay_factor': '1.0',
            'content': 'no ip vrf TEST'
        },
        {
            'type': service_classes['Netmiko Validation Service'],
            'name': 'netmiko_check_no_vrf_TEST',
            'description': 'Check that the vrf "TEST" is NOT configured',
            'vendor': 'Cisco',
            'operating_system': 'IOS',
            'driver': 'cisco_ios',
            'command1': 'show ip vrf',
            'content_match1': '^((?!TEST).)*$',
            'content_match_regex1': 'y'
        },
    ):
        factory(service.pop('type'), **service)


def create_napalm_service():
    factory(NapalmConfigService, **{
        'name': 'napalm_create_vrf_TEST',
        'description': 'Create a VRF "TEST" with Napalm',
        'vendor': 'Cisco',
        'operating_system': 'IOS',
        'content_type': 'simple',
        'action': 'load_merge_candidate',
        'content': 'ip vrf TEST'
    })


def create_other_services():
    factory(NapalmGettersService, **{
        'name': 'service_napalm_getter',
        'description': 'Getters: facts / Interfaces / Interfaces IP',
        'content_match': '',
        'getters': ['get_facts', 'get_interfaces', 'get_interfaces_ip']
    })
    factory(RestCallService, **{
        'name': 'GET_router8',
        'description': 'Use GET ReST call on router8',
        'content_match': '',
        'call_type': 'GET',
        'url': 'http://127.0.0.1:5000/rest/object/device/router8',
        'payload': ''
    })


def create_netmiko_tasks():
    services = [
        retrieve(Service, name=service_name) for service_name in (
            'netmiko_create_vrf_TEST',
            'netmiko_check_vrf_TEST',
            'netmiko_delete_vrf_TEST',
            'netmiko_check_no_vrf_TEST'
        )
    ]
    for service in services:
        factory(ServiceTask, **{
            'name': f'task_{service.name}',
            'devices': [retrieve(Device, name='router8')],
            'waiting_time': 3 if service.name == 'delete_vrf_TEST' else 0,
            'job': service,
            'do_not_run': 'y',
            'user': retrieve(User, name='cisco')
        })


def create_napalm_tasks():
    device = retrieve(Device, name='router8')
    user = retrieve(User, name='cisco')
    factory(ServiceTask, **{
        'name': 'task_napalm_create_vrf_TEST',
        'job': retrieve(Service, name='napalm_create_vrf_TEST'),
        'devices': [device],
        'do_not_run': 'y',
        'user': user
    })
    factory(ServiceTask, **{
        'name': 'task_napalm_rollback',
        'job': retrieve(Service, name='Napalm Rollback'),
        'devices': [device],
        'do_not_run': 'y',
        'user': user
    })


def create_other_tasks():
    device = retrieve(Device, name='router8')
    user = retrieve(User, name='cisco')
    factory(ServiceTask, **{
        'name': 'task_service_napalm_getter',
        'waiting_time': '0',
        'job': retrieve(Service, name='service_napalm_getter'),
        'devices': [device],
        'do_not_run': 'y',
        'user': user
    })
    factory(ServiceTask, **{
        'name': 'task_GET_router8',
        'job': retrieve(Service, name='GET_router8'),
        'devices': [],
        'do_not_run': 'y',
        'user': user
    })


def create_netmiko_workflow():
    tasks = [
        retrieve(Task, name=task_name) for task_name in (
            'task_netmiko_create_vrf_TEST',
            'task_netmiko_check_vrf_TEST',
            'task_netmiko_delete_vrf_TEST',
            'task_netmiko_check_no_vrf_TEST'
        )
    ]
    workflow = factory(Workflow, **{
        'name': 'Netmiko_VRF_workflow',
        'description': 'Create and delete a VRF with Netmiko',
        'tasks': tasks
    })
    for i in range(len(tasks) - 1):
        factory(WorkflowEdge, **{
            'name': f'{tasks[i].name} -> {tasks[i + 1].name}',
            'workflow': workflow,
            'type': True,
            'source': tasks[i],
            'destination': tasks[i + 1]
        })
    workflow.start_task, workflow.end_task = tasks[0].id, tasks[-1].id
    factory(WorkflowTask, **{
        'name': 'task_netmiko_VRF_workflow',
        'job': workflow,
        'do_not_run': 'y',
        'user': retrieve(User, name='cisco')
    })


def create_napalm_workflow():
    tasks = [
        retrieve(Task, name=task_name) for task_name in (
            'task_napalm_create_vrf_TEST',
            'task_netmiko_check_vrf_TEST',
            'task_napalm_rollback',
            'task_netmiko_check_no_vrf_TEST'
        )
    ]
    workflow = factory(Workflow, **{
        'name': 'Napalm_VRF_workflow',
        'description': 'Create and delete a VRF with Napalm',
        'tasks': tasks
    })
    for i in range(len(tasks) - 1):
        factory(WorkflowEdge, **{
            'name': f'{tasks[i].name} -> {tasks[i + 1].name}',
            'workflow': workflow,
            'type': True,
            'source': tasks[i],
            'destination': tasks[i + 1]
        })
    workflow.start_task, workflow.end_task = tasks[0].id, tasks[-1].id
    factory(WorkflowTask, **{
        'name': 'task_napalm_VRF_workflow',
        'job': workflow,
        'do_not_run': 'y',
        'user': retrieve(User, name='cisco')
    })


def create_other_workflow():
    tasks = [
        retrieve(Task, name=task_name) for task_name in (
            'task_service_napalm_getter',
            'task_GET_router8',
        )
    ]
    workflow = factory(Workflow, **{
        'name': 'custom_workflow',
        'description': 'ReST call, Napalm getters, etc',
        'tasks': tasks
    })
    for i in range(len(tasks) - 1):
        factory(WorkflowEdge, **{
            'name': f'{tasks[i].name} -> {tasks[i + 1].name}',
            'workflow': workflow,
            'type': True,
            'source': tasks[i],
            'destination': tasks[i + 1]
        })
    workflow.start_task, workflow.end_task = tasks[0].id, tasks[-1].id
    factory(WorkflowTask, **{
        'name': 'task_custom_workflow',
        'job': workflow,
        'do_not_run': 'y',
        'user': retrieve(User, name='cisco')
    })


def create_default_services():
    create_netmiko_services()
    create_napalm_service()
    create_other_services()


def create_default_tasks():
    create_netmiko_tasks()
    create_napalm_tasks()
    create_other_tasks()


def create_default_workflows():
    create_netmiko_workflow()
    create_napalm_workflow()
    create_other_workflow()
