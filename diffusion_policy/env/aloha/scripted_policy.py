import numpy as np
import matplotlib.pyplot as plt
from pyquaternion import Quaternion

from diffusion_policy.env.aloha.constants import SIM_TASK_CONFIGS
from diffusion_policy.env.aloha.ee_sim_env import make_ee_sim_env

import IPython
e = IPython.embed


class BasePolicy:
    def __init__(self, inject_noise=False):
        self.inject_noise = inject_noise
        self.step_count = 0
        self.left_trajectory = None
        self.right_trajectory = None

    def generate_trajectory(self, ts_first):
        raise NotImplementedError

    @staticmethod
    def interpolate(curr_waypoint, next_waypoint, t):
        t_frac = (t - curr_waypoint["t"]) / (next_waypoint["t"] - curr_waypoint["t"])
        curr_xyz = curr_waypoint['xyz']
        curr_quat = curr_waypoint['quat']
        curr_grip = curr_waypoint['gripper']
        next_xyz = next_waypoint['xyz']
        next_quat = next_waypoint['quat']
        next_grip = next_waypoint['gripper']
        xyz = curr_xyz + (next_xyz - curr_xyz) * t_frac
        quat = curr_quat + (next_quat - curr_quat) * t_frac
        gripper = curr_grip + (next_grip - curr_grip) * t_frac
        return xyz, quat, gripper

    def __call__(self, ts):
        # generate trajectory at first timestep, then open-loop execution
        if self.step_count == 0:
            self.generate_trajectory(ts)

        # obtain left and right waypoints
        if self.left_trajectory[0]['t'] == self.step_count:
            self.curr_left_waypoint = self.left_trajectory.pop(0)
        next_left_waypoint = self.left_trajectory[0]

        if self.right_trajectory[0]['t'] == self.step_count:
            self.curr_right_waypoint = self.right_trajectory.pop(0)
        next_right_waypoint = self.right_trajectory[0]

        # interpolate between waypoints to obtain current pose and gripper command
        left_xyz, left_quat, left_gripper = self.interpolate(self.curr_left_waypoint, next_left_waypoint, self.step_count)
        right_xyz, right_quat, right_gripper = self.interpolate(self.curr_right_waypoint, next_right_waypoint, self.step_count)

        # Inject noise
        if self.inject_noise:
            scale = 0.01
            left_xyz = left_xyz + np.random.uniform(-scale, scale, left_xyz.shape)
            right_xyz = right_xyz + np.random.uniform(-scale, scale, right_xyz.shape)

        action_left = np.concatenate([left_xyz, left_quat, [left_gripper]])
        action_right = np.concatenate([right_xyz, right_quat, [right_gripper]])

        self.step_count += 1
        return np.concatenate([action_left, action_right])



class SingleArmBasePolicy:
    def __init__(self, inject_noise=False):
        self.inject_noise = inject_noise
        self.step_count = 0
        self.left_trajectory = None
        self.right_trajectory = None

    def generate_trajectory(self, ts_first):
        raise NotImplementedError

    @staticmethod
    def interpolate(curr_waypoint, next_waypoint, t):
        t_frac = (t - curr_waypoint["t"]) / (next_waypoint["t"] - curr_waypoint["t"])
        curr_xyz = curr_waypoint['xyz']
        curr_quat = curr_waypoint['quat']
        curr_grip = curr_waypoint['gripper']
        next_xyz = next_waypoint['xyz']
        next_quat = next_waypoint['quat']
        next_grip = next_waypoint['gripper']
        xyz = curr_xyz + (next_xyz - curr_xyz) * t_frac
        quat = curr_quat + (next_quat - curr_quat) * t_frac
        gripper = curr_grip + (next_grip - curr_grip) * t_frac
        return xyz, quat, gripper

    def __call__(self, ts):
        # generate trajectory at first timestep, then open-loop execution
        if self.step_count == 0:
            self.generate_trajectory(ts)

        # # obtain left and right waypoints
        # if self.left_trajectory[0]['t'] == self.step_count:
        #     self.curr_left_waypoint = self.left_trajectory.pop(0)
        # next_left_waypoint = self.left_trajectory[0]

        if self.right_trajectory[0]['t'] == self.step_count:
            self.curr_right_waypoint = self.right_trajectory.pop(0)
        next_right_waypoint = self.right_trajectory[0]

        # interpolate between waypoints to obtain current pose and gripper command
        # left_xyz, left_quat, left_gripper = self.interpolate(self.curr_left_waypoint, next_left_waypoint, self.step_count)
        right_xyz, right_quat, right_gripper = self.interpolate(self.curr_right_waypoint, next_right_waypoint, self.step_count)

        # Inject noise
        if self.inject_noise:
            scale = 0.03
            # left_xyz = left_xyz + np.random.uniform(-scale, scale, left_xyz.shape)
            right_xyz = right_xyz + np.random.uniform(-scale, scale, right_xyz.shape)

        # action_left = np.concatenate([left_xyz, left_quat, [left_gripper]])
        action_right = np.concatenate([right_xyz, right_quat, [right_gripper]])

        self.step_count += 1
        return action_right#np.concatenate([action_left, action_right])

class PickAndPlaceAtTwoModesPolicyLargeRand(BasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        box_info = np.array(ts_first.observation['env_state'])
        box_xyz = box_info[:3]
        box_quat = box_info[3:]
        from diffusion_policy.env.aloha.ee_sim_env import get_target_pose
        box_xyz_drop = get_target_pose(box_xyz)
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat_right = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_right = gripper_pick_quat_right * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        gripper_pick_quat_left = Quaternion(init_mocap_pose_left[3:])
        gripper_pick_quat_left = gripper_pick_quat_left * Quaternion(axis=[0.0, 1.0, 0.0], degrees=60)

        meet_left_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)
        meet_right_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)

        meet_xyz = np.array([0, 0.5, 0.25])

        place_xyz = np.array([0, 0.5, box_xyz[2]])
        place_quat = np.array(box_quat)

        gripper_place_quat = Quaternion(init_mocap_pose_left[3:])


        from scipy.spatial.transform import Rotation as R

        # Start orientation
        base_rot = R.from_quat(init_mocap_pose_left[3:])

        # Define some small rotations
        rot1 = base_rot * R.from_euler('z', 30, degrees=True)   # rotate 30° around Z
        rot2 = base_rot * R.from_euler('y', -30, degrees=True)  # rotate -30° around Y
        rot3 = base_rot * R.from_euler('x', 30, degrees=True)   # rotate 30° around X
        rot_back = base_rot                                     # back to original

        self.left_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_left[:3], "quat": base_rot.as_quat(), "gripper": 0},

            {"t": 100, "xyz": init_mocap_pose_left[:3] + np.array([0.0, 0.05, 0.05]), "quat": rot1.as_quat(), "gripper": 0},
            {"t": 150, "xyz": init_mocap_pose_left[:3] + np.array([0.05, 0.05, 0.1]), "quat": rot2.as_quat(), "gripper": 0},
            {"t": 200, "xyz": init_mocap_pose_left[:3] + np.array([0.05, -0.05, 0.1]), "quat": rot3.as_quat(), "gripper": 0},
            {"t": 250, "xyz": init_mocap_pose_left[:3] + np.array([-0.05, -0.05, 0.05]), "quat": rot2.as_quat(), "gripper": 0},
            {"t": 300, "xyz": init_mocap_pose_left[:3], "quat": rot_back.as_quat(), "gripper": 0},

            {"t": 400, "xyz": init_mocap_pose_left[:3] + np.array([0.0, 0.0, 0.05]), "quat": rot1.as_quat(), "gripper": 0},
            {"t": 500, "xyz": init_mocap_pose_left[:3], "quat": base_rot.as_quat(), "gripper": 0},
        ]




        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 100, "xyz": box_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # approach the cube
            {"t": 150, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # go down
            {"t": 170, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # close gripper
            {"t": 200, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 220, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # move to right
            {"t": 270, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 320, "xyz": box_xyz_drop + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach the cube
            {"t": 350, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # go down
            {"t": 400, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
            {"t": 450, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
            {"t": 500, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
        ]

class PickAndPlaceOriginPolicyLargeRand(BasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        box_info = np.array(ts_first.observation['env_state'])
        box_xyz = box_info[:3]
        box_quat = box_info[3:]

        box_xyz_drop = [0.1, 0.5, box_xyz[-1]]
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat_right = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_right = gripper_pick_quat_right * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        gripper_pick_quat_left = Quaternion(init_mocap_pose_left[3:])
        gripper_pick_quat_left = gripper_pick_quat_left * Quaternion(axis=[0.0, 1.0, 0.0], degrees=60)

        meet_left_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)
        meet_right_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)

        meet_xyz = np.array([0, 0.5, 0.25])

        place_xyz = np.array([0, 0.5, box_xyz[2]])
        place_quat = np.array(box_quat)

        gripper_place_quat = Quaternion(init_mocap_pose_left[3:])


        self.left_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep
            {"t": 500, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep
        ]

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 100, "xyz": box_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # approach the cube
            {"t": 150, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # go down
            {"t": 170, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # close gripper
            {"t": 200, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 220, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # move to right
            {"t": 270, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 320, "xyz": box_xyz_drop + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach the cube
            {"t": 350, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # go down
            {"t": 400, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
            {"t": 450, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
            {"t": 500, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
        ]

class SingleArmPickAndPlaceOriginPolicyLargeRand(SingleArmBasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        # init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        box_info = np.array(ts_first.observation['env_state'])
        box_xyz = box_info[:3]
        box_quat = box_info[3:]

        box_xyz_drop = [0.1, 0.5, box_xyz[-1]]
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat_right = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_right = gripper_pick_quat_right * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        # gripper_pick_quat_left = Quaternion(init_mocap_pose_left[3:])
        # gripper_pick_quat_left = gripper_pick_quat_left * Quaternion(axis=[0.0, 1.0, 0.0], degrees=60)

        # meet_left_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)
        meet_right_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)

        meet_xyz = np.array([0, 0.5, 0.25])

        place_xyz = np.array([0, 0.5, box_xyz[2]])
        place_quat = np.array(box_quat)

        # gripper_place_quat = Quaternion(init_mocap_pose_left[3:])

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 100, "xyz": box_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # approach the cube
            {"t": 150, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # go down
            {"t": 170, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # close gripper
            {"t": 200, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 220, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # move to right
            {"t": 270, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 320, "xyz": box_xyz_drop + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach the cube
            {"t": 350, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # go down
            {"t": 400, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
            {"t": 450, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
            {"t": 500, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
        ]


class SingleArmPickAndPlaceTwoModesPolicyLargeRand(SingleArmBasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        # init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        box_info = np.array(ts_first.observation['env_state'])
        box_xyz = box_info[:3]
        box_quat = box_info[3:]

        from diffusion_policy.env.aloha.ee_sim_env import get_target_pose
        box_xyz_drop = get_target_pose(box_xyz)
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat_right = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_right = gripper_pick_quat_right * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        # gripper_pick_quat_left = Quaternion(init_mocap_pose_left[3:])
        # gripper_pick_quat_left = gripper_pick_quat_left * Quaternion(axis=[0.0, 1.0, 0.0], degrees=60)

        # meet_left_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)
        meet_right_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)

        meet_xyz = np.array([0, 0.5, 0.25])

        place_xyz = np.array([0, 0.5, box_xyz[2]])
        place_quat = np.array(box_quat)

        # gripper_place_quat = Quaternion(init_mocap_pose_left[3:])

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 100, "xyz": box_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # approach the cube
            {"t": 150, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # go down
            {"t": 170, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # close gripper
            {"t": 200, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 220, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # move to right
            {"t": 270, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 320, "xyz": box_xyz_drop + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach the cube
            {"t": 350, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # go down
            {"t": 400, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
            {"t": 450, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
            {"t": 500, "xyz": box_xyz_drop + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
        ]



class PickAndPlaceSamePosPolicyLargeRand(BasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        box_info = np.array(ts_first.observation['env_state'])
        box_xyz = box_info[:3]
        box_quat = box_info[3:]
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat_right = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_right = gripper_pick_quat_right * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        gripper_pick_quat_left = Quaternion(init_mocap_pose_left[3:])
        gripper_pick_quat_left = gripper_pick_quat_left * Quaternion(axis=[0.0, 1.0, 0.0], degrees=60)



        meet_left_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)
        meet_right_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)

        meet_xyz = np.array([0, 0.5, 0.25])

        place_xyz = np.array([0, 0.5, box_xyz[2]])
        place_quat = np.array(box_quat)

        gripper_place_quat = Quaternion(init_mocap_pose_left[3:])


        self.left_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep
            {"t": 500, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep
        ]

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 100, "xyz": box_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # approach the cube
            {"t": 150, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # go down
            {"t": 170, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # close gripper
            {"t": 200, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 250, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # move to right
            {"t": 300, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 350, "xyz": box_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach the cube
            {"t": 400, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # go down
            {"t": 450, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
            {"t": 500, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
        ]

class PickAndPlaceHistoryTransferPolicyLargeRand(BasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        box_info = np.array(ts_first.observation['env_state'])
        box_xyz = box_info[:3]
        box_quat = box_info[3:]
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat_right = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_right = gripper_pick_quat_right * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        gripper_pick_quat_left = Quaternion(init_mocap_pose_left[3:])
        gripper_pick_quat_left = gripper_pick_quat_left * Quaternion(axis=[0.0, 1.0, 0.0], degrees=60)



        meet_left_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)
        meet_right_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)

        meet_xyz = np.array([0, 0.5, 0.25])

        place_xyz = np.array([0, 0.5, box_xyz[2]])
        place_quat = np.array(box_quat)

        gripper_place_quat = Quaternion(init_mocap_pose_left[3:])


        self.left_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep
            {"t": 150, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 1}, # approach meet position
            {"t": 310, "xyz": meet_xyz + np.array([0.02, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 1}, # move to meet position
            {"t": 360, "xyz": meet_xyz + np.array([0.02, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 0}, # close gripper
            {"t": 410, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": np.array([1, 0, 0, 0]), "gripper": 0}, # move left
            # drop cube
            {"t": 450, "xyz": place_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_left.elements, "gripper": 0}, # approach the cube
            {"t": 500, "xyz": place_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_left.elements, "gripper": 0}, # go down
            {"t": 550, "xyz": place_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_left.elements, "gripper": 1}, # open gripper

            {"t": 600, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep


            {"t": 650, "xyz": place_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_left.elements, "gripper": 1}, # approach the cube
            {"t": 700, "xyz": place_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_left.elements, "gripper": 1}, # go down
            {"t": 750, "xyz": place_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_left.elements, "gripper": 0}, # close gripper

            {"t": 800, "xyz": meet_xyz + np.array([-0.1, 0, 0]), "quat": gripper_pick_quat_left.elements, "gripper": 0}, # approach meet position
            {"t": 850, "xyz": meet_xyz + np.array([0.02, 0, 0]), "quat": gripper_pick_quat_left.elements, "gripper": 0}, # move to meet position
            {"t": 900, "xyz": meet_xyz + np.array([0.02, 0, 0]), "quat": gripper_pick_quat_left.elements, "gripper": 1}, # open gripper
            {"t": 950, "xyz": meet_xyz + np.array([-0.1, 0, 0]), "quat": np.array([1, 0, 0, 0]), "gripper": 1}, # move left
        ]

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 100, "xyz": box_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # approach the cube
            {"t": 150, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # go down
            {"t": 170, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # close gripper
            {"t": 200, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 220, "xyz": meet_xyz, "quat": gripper_pick_quat_right.elements, "gripper": 0}, # move to meet position
            {"t": 360, "xyz": meet_xyz, "quat": gripper_pick_quat_right.elements, "gripper": 1}, # open gripper
            {"t": 410, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # move to right
            {"t": 450, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep

            {"t": 750, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep

            {"t": 800, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": meet_right_quat.elements, "gripper": 1}, # approach meet position
            {"t": 850, "xyz": meet_xyz + np.array([0.0, 0, 0]), "quat": meet_right_quat.elements, "gripper": 1}, # move to meet position
            {"t": 900, "xyz": meet_xyz+ np.array([0.0, 0, 0]), "quat": meet_right_quat.elements, "gripper": 0}, # close gripper
            {"t": 950, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": meet_right_quat.elements, "gripper": 0}, # move to right
        ]


class PickAndHistoryTransferPolicyLargeRand(BasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        box_info = np.array(ts_first.observation['env_state'])
        box_xyz = box_info[:3]
        box_quat = box_info[3:]
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat = gripper_pick_quat * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        gripper_pick_quat_left = Quaternion(init_mocap_pose_left[3:])
        gripper_pick_quat_left = gripper_pick_quat_left * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        meet_left_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)
        meet_right_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)

        meet_xyz = np.array([0, 0.5, 0.25])

        self.left_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep
            {"t": 150, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 1}, # approach meet position
            {"t": 310, "xyz": meet_xyz + np.array([0.02, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 1}, # move to meet position
            {"t": 360, "xyz": meet_xyz + np.array([0.02, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 0}, # close gripper
            {"t": 410, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": np.array([1, 0, 0, 0]), "gripper": 0}, # move left
            {"t": 480, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": np.array([1, 0, 0, 0]), "gripper": 0}, # stay
            {"t": 500, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 0}, # approach meet position
            {"t": 650, "xyz": meet_xyz + np.array([0.02, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 0}, # move to meet position
            {"t": 750, "xyz": meet_xyz + np.array([0.02, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 1}, # open gripper
            {"t": 780, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": np.array([1, 0, 0, 0]), "gripper": 1}, # move left
            {"t": 800, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": np.array([1, 0, 0, 0]), "gripper": 1}, # stay
        ]

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 100, "xyz": box_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat.elements, "gripper": 1}, # approach the cube
            {"t": 150, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat.elements, "gripper": 1}, # go down
            {"t": 170, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat.elements, "gripper": 0}, # close gripper
            {"t": 200, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 0}, # approach meet position
            {"t": 220, "xyz": meet_xyz, "quat": gripper_pick_quat.elements, "gripper": 0}, # move to meet position
            {"t": 360, "xyz": meet_xyz, "quat": gripper_pick_quat.elements, "gripper": 1}, # open gripper
            {"t": 410, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 1}, # move to right
            {"t": 480, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 1}, # stay
            {"t": 500, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 1}, # approach meet position
            {"t": 650, "xyz": meet_xyz + np.array([0.01, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 1}, # move to meet position
            {"t": 720, "xyz": meet_xyz+ np.array([0.01, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 0}, # close gripper
            {"t": 780, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 0}, # move to right
            {"t": 800, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 0}, # stay
        ]


class PickAndTransferPolicyLargeRand(BasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        box_info = np.array(ts_first.observation['env_state'])
        box_xyz = box_info[:3]
        box_quat = box_info[3:]
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat = gripper_pick_quat * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        meet_left_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)

        meet_xyz = np.array([0, 0.5, 0.25])

        self.left_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep
            {"t": 150, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 1}, # approach meet position
            {"t": 310, "xyz": meet_xyz + np.array([0.02, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 1}, # move to meet position
            {"t": 360, "xyz": meet_xyz + np.array([0.02, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 0}, # close gripper
            {"t": 410, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": np.array([1, 0, 0, 0]), "gripper": 0}, # move left
            {"t": 480, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": np.array([1, 0, 0, 0]), "gripper": 0}, # stay
        ]

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 100, "xyz": box_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat.elements, "gripper": 1}, # approach the cube
            {"t": 150, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat.elements, "gripper": 1}, # go down
            {"t": 170, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat.elements, "gripper": 0}, # close gripper
            {"t": 200, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 0}, # approach meet position
            {"t": 220, "xyz": meet_xyz, "quat": gripper_pick_quat.elements, "gripper": 0}, # move to meet position
            {"t": 360, "xyz": meet_xyz, "quat": gripper_pick_quat.elements, "gripper": 1}, # open gripper
            {"t": 410, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 1}, # move to right
            {"t": 480, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 1}, # stay
        ]

class PickAndTransferPolicy(BasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        box_info = np.array(ts_first.observation['env_state'])
        box_xyz = box_info[:3]
        box_quat = box_info[3:]
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat = gripper_pick_quat * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        meet_left_quat = Quaternion(axis=[1.0, 0.0, 0.0], degrees=90)

        meet_xyz = np.array([0, 0.5, 0.25])

        self.left_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep
            {"t": 100, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 1}, # approach meet position
            {"t": 260, "xyz": meet_xyz + np.array([0.02, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 1}, # move to meet position
            {"t": 310, "xyz": meet_xyz + np.array([0.02, 0, -0.02]), "quat": meet_left_quat.elements, "gripper": 0}, # close gripper
            {"t": 360, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": np.array([1, 0, 0, 0]), "gripper": 0}, # move left
            {"t": 400, "xyz": meet_xyz + np.array([-0.1, 0, -0.02]), "quat": np.array([1, 0, 0, 0]), "gripper": 0}, # stay
        ]

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 90, "xyz": box_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat.elements, "gripper": 1}, # approach the cube
            {"t": 130, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat.elements, "gripper": 1}, # go down
            {"t": 170, "xyz": box_xyz + np.array([0, 0, -0.015]), "quat": gripper_pick_quat.elements, "gripper": 0}, # close gripper
            {"t": 200, "xyz": meet_xyz + np.array([0.05, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 0}, # approach meet position
            {"t": 220, "xyz": meet_xyz, "quat": gripper_pick_quat.elements, "gripper": 0}, # move to meet position
            {"t": 310, "xyz": meet_xyz, "quat": gripper_pick_quat.elements, "gripper": 1}, # open gripper
            {"t": 360, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 1}, # move to right
            {"t": 400, "xyz": meet_xyz + np.array([0.1, 0, 0]), "quat": gripper_pick_quat.elements, "gripper": 1}, # stay
        ]

class InsertionPolicyLargeRand(BasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        peg_info = np.array(ts_first.observation['env_state'])[:7]
        peg_xyz = peg_info[:3]
        peg_quat = peg_info[3:]

        socket_info = np.array(ts_first.observation['env_state'])[7:]
        socket_xyz = socket_info[:3]
        socket_quat = socket_info[3:]

        gripper_pick_quat_right = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_right = gripper_pick_quat_right * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        gripper_pick_quat_left = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_left = gripper_pick_quat_left * Quaternion(axis=[0.0, 1.0, 0.0], degrees=60)

        meet_xyz = np.array([0, 0.5, 0.15])
        lift_right = 0.00715

        self.left_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep
            {"t": 30, "xyz": socket_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_left.elements, "gripper": 1}, # approach the cube
            {"t": 190, "xyz": socket_xyz + np.array([0, 0, -0.03]), "quat": gripper_pick_quat_left.elements, "gripper": 1}, # go down
            {"t": 220, "xyz": socket_xyz + np.array([0, 0, -0.03]), "quat": gripper_pick_quat_left.elements, "gripper": 0}, # close gripper
            {"t": 285, "xyz": meet_xyz + np.array([-0.1, 0, 0]), "quat": gripper_pick_quat_left.elements, "gripper": 0}, # approach meet position
            {"t": 340, "xyz": meet_xyz + np.array([-0.05, 0, 0]), "quat": gripper_pick_quat_left.elements,"gripper": 0},  # insertion
            {"t": 400, "xyz": meet_xyz + np.array([-0.05, 0, 0]), "quat": gripper_pick_quat_left.elements, "gripper": 0},  # insertion
        ]

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 30, "xyz": peg_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # approach the cube
            {"t": 190, "xyz": peg_xyz + np.array([0, 0, -0.03]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # go down
            {"t": 220, "xyz": peg_xyz + np.array([0, 0, -0.03]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # close gripper
            {"t": 285, "xyz": meet_xyz + np.array([0.1, 0, lift_right]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 340, "xyz": meet_xyz + np.array([0.05, 0, lift_right]), "quat": gripper_pick_quat_right.elements, "gripper": 0},  # insertion
            {"t": 400, "xyz": meet_xyz + np.array([0.05, 0, lift_right]), "quat": gripper_pick_quat_right.elements, "gripper": 0},  # insertion

        ]

class InsertionPolicy(BasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation['mocap_pose_right']
        init_mocap_pose_left = ts_first.observation['mocap_pose_left']

        peg_info = np.array(ts_first.observation['env_state'])[:7]
        peg_xyz = peg_info[:3]
        peg_quat = peg_info[3:]

        socket_info = np.array(ts_first.observation['env_state'])[7:]
        socket_xyz = socket_info[:3]
        socket_quat = socket_info[3:]

        gripper_pick_quat_right = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_right = gripper_pick_quat_right * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        gripper_pick_quat_left = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat_left = gripper_pick_quat_left * Quaternion(axis=[0.0, 1.0, 0.0], degrees=60)

        meet_xyz = np.array([0, 0.5, 0.15])
        lift_right = 0.00715

        self.left_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_left[:3], "quat": init_mocap_pose_left[3:], "gripper": 0}, # sleep
            {"t": 120, "xyz": socket_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_left.elements, "gripper": 1}, # approach the cube
            {"t": 170, "xyz": socket_xyz + np.array([0, 0, -0.03]), "quat": gripper_pick_quat_left.elements, "gripper": 1}, # go down
            {"t": 220, "xyz": socket_xyz + np.array([0, 0, -0.03]), "quat": gripper_pick_quat_left.elements, "gripper": 0}, # close gripper
            {"t": 285, "xyz": meet_xyz + np.array([-0.1, 0, 0]), "quat": gripper_pick_quat_left.elements, "gripper": 0}, # approach meet position
            {"t": 340, "xyz": meet_xyz + np.array([-0.05, 0, 0]), "quat": gripper_pick_quat_left.elements,"gripper": 0},  # insertion
            {"t": 400, "xyz": meet_xyz + np.array([-0.05, 0, 0]), "quat": gripper_pick_quat_left.elements, "gripper": 0},  # insertion
        ]

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0}, # sleep
            {"t": 120, "xyz": peg_xyz + np.array([0, 0, 0.08]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # approach the cube
            {"t": 170, "xyz": peg_xyz + np.array([0, 0, -0.03]), "quat": gripper_pick_quat_right.elements, "gripper": 1}, # go down
            {"t": 220, "xyz": peg_xyz + np.array([0, 0, -0.03]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # close gripper
            {"t": 285, "xyz": meet_xyz + np.array([0.1, 0, lift_right]), "quat": gripper_pick_quat_right.elements, "gripper": 0}, # approach meet position
            {"t": 340, "xyz": meet_xyz + np.array([0.05, 0, lift_right]), "quat": gripper_pick_quat_right.elements, "gripper": 0},  # insertion
            {"t": 400, "xyz": meet_xyz + np.array([0.05, 0, lift_right]), "quat": gripper_pick_quat_right.elements, "gripper": 0},  # insertion

        ]


def test_policy(task_name):
    # example rolling out pick_and_transfer policy
    onscreen_render = True
    inject_noise = False

    # setup the environment
    episode_len = SIM_TASK_CONFIGS[task_name]['episode_len']
    if 'sim_transfer_cube' in task_name:
        env = make_ee_sim_env('sim_transfer_cube')
    elif 'sim_insertion' in task_name:
        env = make_ee_sim_env('sim_insertion')
    else:
        raise NotImplementedError

    for episode_idx in range(2):
        ts = env.reset()
        episode = [ts]
        if onscreen_render:
            ax = plt.subplot()
            plt_img = ax.imshow(ts.observation['images']['angle'])
            plt.ion()

        policy = PickAndTransferPolicy(inject_noise)
        for step in range(episode_len):
            action = policy(ts)
            ts = env.step(action)
            episode.append(ts)
            if onscreen_render:
                plt_img.set_data(ts.observation['images']['angle'])
                plt.pause(0.02)
        plt.close()

        episode_return = np.sum([ts.reward for ts in episode[1:]])
        if episode_return > 0:
            print(f"{episode_idx=} Successful, {episode_return=}")
        else:
            print(f"{episode_idx=} Failed")


if __name__ == '__main__':
    test_task_name = 'sim_transfer_cube_scripted'
    test_policy(test_task_name)
