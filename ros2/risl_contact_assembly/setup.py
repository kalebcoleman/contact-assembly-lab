"""Install the brick assembly package and its launch, config and structure files."""

from glob import glob

from setuptools import find_packages, setup

package_name = "risl_contact_assembly"

setup(
    name=package_name,
    version="0.2.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/structures", glob("structures/*.json")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Kaleb Coleman",
    maintainer_email="kalebcoleman@users.noreply.github.com",
    description="Known-position LEGO brick assembly for a UR5e with an RG2.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "assembly_executor = risl_contact_assembly.executor:main",
            "record_poses = risl_contact_assembly.record_poses:main",
            "fake_gripper = risl_contact_assembly.fake_gripper:main",
        ],
    },
)
