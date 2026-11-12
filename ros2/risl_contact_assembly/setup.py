from glob import glob

from setuptools import find_packages, setup

package_name = 'risl_contact_assembly'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/fixtures', glob('fixtures/*.json')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Kaleb Coleman',
    maintainer_email='kalebcoleman@users.noreply.github.com',
    description='Known-pose UR5e contact assembly rehearsal with mock hardware.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'assembly_executor = risl_contact_assembly.executor:main',
            'fake_gripper = risl_contact_assembly.fake_gripper:main',
            'record_joint_states = risl_contact_assembly.record_joint_states:main',
        ],
    },
)
