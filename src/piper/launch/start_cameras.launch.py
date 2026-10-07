import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import GroupAction, IncludeLaunchDescription, TimerAction
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
        GroupAction(
            scoped=True,
            actions=[
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
            ],
        ),
        # Orbbec SDK 在两台同型号设备并发初始化时会竞争设备锁。
        # 右相机错峰启动，等待左相机完成枚举和流配置。
        TimerAction(
            period=5.0,
            actions=[
                GroupAction(
                    scoped=True,
                    actions=[
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
                    ],
                ),
            ],
        ),
        # 三种相机驱动并发枚举 USB 设备时也可能发生初始化竞争。
        # 等两台 Orbbec 完成初始化后再启动第三视角 D455。
        TimerAction(
            period=10.0,
            actions=[
                GroupAction(
                    scoped=True,
                    actions=[
                        IncludeLaunchDescription(
                            PythonLaunchDescriptionSource(realsense_launch),
                            launch_arguments={
                                'camera_namespace': 'camera_third_view',
                                'camera_name': 'D455_1',
                                # RealSense 的 launch 参数会对纯数字文本做类型推断；额外引号确保
                                # serial_no 仍按字符串传入，否则节点会因参数类型错误退出。
                                'serial_no': "'338122301303'",
                            }.items(),
                        ),
                    ],
                ),
            ],
        ),
    ])
