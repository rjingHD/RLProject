from flow.envs import Env
from gym.spaces.box import Box
from flow.core.rewards import desired_velocity
from flow.controllers import IDMController, ContinuousRouter, RLController
from flow.core.experiment import Experiment
from flow.core.params import SumoParams, EnvParams, InitialConfig, NetParams, SumoCarFollowingParams
from flow.core.params import VehicleParams
from flow.networks.figure_eight import FigureEightNetwork, ADDITIONAL_NET_PARAMS
import numpy as np
import json
import ray
from ray.rllib.agents.registry import get_agent_class
from ray.tune import run_experiments
from ray.tune.registry import register_env

from flow.envs import CustomEnv
from flow.utils.registry import make_create_env
from flow.utils.rllib import FlowParamsEncoder



additional_net_params = ADDITIONAL_NET_PARAMS.copy()
# time horizon of a single rollout
HORIZON = 1500
# number of rollouts per training iteration
N_ROLLOUTS = 20
# number of parallel workers
N_CPUS = 2

vehicles = VehicleParams()
for i in range(7):
    vehicles.add(
        veh_id='human' + str(i),
        acceleration_controller=(IDMController, {
            'noise': 0.2
        }),
        routing_controller=(ContinuousRouter, {}),
        car_following_params=SumoCarFollowingParams(
            speed_mode="obey_safe_speed",
            decel=1.5,
        ),
        num_vehicles=1)
    vehicles.add(
        veh_id='rl' + str(i),
        acceleration_controller=(RLController, {}),
        routing_controller=(ContinuousRouter, {}),
        car_following_params=SumoCarFollowingParams(
            speed_mode="obey_safe_speed",
            decel=1.5,
        ),
        num_vehicles=1)


# vehicles.add(
#     veh_id='human',
#     acceleration_controller=(IDMController, {
#         'noise': 0.2
#     }),
#     routing_controller=(ContinuousRouter, {}),
#     car_following_params=SumoCarFollowingParams(
#         speed_mode="obey_safe_speed",
#         decel=1.5,
#     ),
#     num_vehicles=6)
# vehicles.add(
#     veh_id='rl',
#     acceleration_controller=(RLController, {}),
#     routing_controller=(ContinuousRouter, {}),
#     car_following_params=SumoCarFollowingParams(
#         speed_mode="obey_safe_speed",
#         decel=1.5,
#     ),
#     num_vehicles=1)
# vehicles.add(
#     veh_id='human2',
#     acceleration_controller=(IDMController, {
#         'noise': 0.2
#     }),
#     routing_controller=(ContinuousRouter, {}),
#     car_following_params=SumoCarFollowingParams(
#         speed_mode="obey_safe_speed",
#         decel=1.5,
#     ),
#     num_vehicles=6)
# vehicles.add(
#     veh_id='rl1',
#     acceleration_controller=(RLController, {}),
#     routing_controller=(ContinuousRouter, {}),
#     car_following_params=SumoCarFollowingParams(
#         speed_mode="obey_safe_speed",
#         decel=1.5,
#     ),
#     num_vehicles=1)

flow_params = dict(
    # name of the experiment
    exp_tag='singleagent_figure_eight',

    # name of the flow environment the experiment is running on
    env_name=CustomEnv,

    # name of the network class the experiment is running on
    network=FigureEightNetwork,

    # simulator that is used by the experiment
    simulator='traci',

    # sumo-related parameters (see flow.core.params.SumoParams)
    sim=SumoParams(
        sim_step=0.1,
        render=False,
        restart_instance=True
    ),

    # environment related parameters (see flow.core.params.EnvParams)
    env=EnvParams(
        horizon=HORIZON,
        additional_params={
            'target_velocity': 20,
            'max_accel': 3,
            'max_decel': 3,
            'sort_vehicles': False
        },
    ),

    # network-related parameters (see flow.core.params.NetParams and the
    # network's documentation or ADDITIONAL_NET_PARAMS component)
    net=NetParams(
        additional_params=ADDITIONAL_NET_PARAMS.copy(),
    ),

    # vehicles to be placed in the network at the start of a rollout (see
    # flow.core.params.VehicleParams)
    veh=vehicles,

    # parameters specifying the positioning of vehicles upon initialization/
    # reset (see flow.core.params.InitialConfig)
    initial=InitialConfig(),
)




def setup_exps():
    """Return the relevant components of an RLlib experiment.

    Returns
    -------
    str
        name of the training algorithm
    str
        name of the gym environment to be trained
    dict
        training configuration parameters
    """
    alg_run = "PPO"

    agent_cls = get_agent_class(alg_run)
    config = agent_cls._default_config.copy()
    config["num_workers"] = N_CPUS
    config["train_batch_size"] = HORIZON * N_ROLLOUTS
    config["gamma"] = 0.999  # discount rate
    config["model"].update({"fcnet_hiddens": [20, 15]})
    config["use_gae"] = True
    config["lambda"] = 0.97
    config["kl_target"] = 0.02
    config["num_sgd_iter"] = 20
    config['lr'] = 1e-4
    config['sgd_minibatch_size'] = 128
    config['clip_actions'] = False  # FIXME(ev) temporary ray bug
    config["horizon"] = HORIZON

    # save the flow params for replay
    flow_json = json.dumps(
        flow_params, cls=FlowParamsEncoder, sort_keys=True, indent=4)
    config['env_config']['flow_params'] = flow_json
    config['env_config']['run'] = alg_run

    create_env, gym_name = make_create_env(params=flow_params, version=0)

    # Register as rllib env
    register_env(gym_name, create_env)
    return alg_run, gym_name, config


alg_run, gym_name, config = setup_exps()
ray.init(num_cpus=N_CPUS + 1)
trials = run_experiments({
    flow_params["exp_tag"]: {
        "run": alg_run,
        "env": gym_name,
        "config": {
            **config
        },
        "checkpoint_freq": 1,
        "checkpoint_at_end": True,
        "max_failures": 999,
        "stop": {
            "training_iteration": 1000,
        },
    }
})