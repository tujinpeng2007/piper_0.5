import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    realsense_launch = os.path.join(
        get_package_share_directory('realsense2_camera'),
        'launch',
        'rs_launch.py',
    )
    orbbec_launch = os.path.join(
        get_package_share_directory('orbbec_camera'),
        'launch',
        'gemini_301_series.launch.py',
    )

    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(realsense_launch),
            launch_arguments={
                'camera_namespace': 'camera_third_view',
                'camera_name': 'D455_1',
                'serial_no': '338122301303',
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(orbbec_launch),
            launch_arguments={
                'camera_name': 'camera_gripper_left',
                'serial_number': 'CV27561000MR',
                'color_width': '640',
                'color_height': '480',
                'depth_width': '640',
                'depth_height': '480',
                'color_fps': '30',
                'depth_fps': '30',
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(orbbec_launch),
            launch_arguments={
                'camera_name': 'camera_gripper_right',
                'serial_number': 'CV275610002H',
                'color_width': '640',
                'color_height': '480',
                'depth_width': '640',
                'depth_height': '480',
                'color_fps': '30',
                'depth_fps': '30',
            }.items(),
        ),
    ])
