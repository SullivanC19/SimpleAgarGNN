import gymnasium as gym
from gymnasium.spaces import Box, Dict, MultiBinary, MultiDiscrete
import pygame

import numpy as np
from scipy.spatial import distance_matrix


class BaseWorld(gym.Env):
    metadata = {"render_modes": ["human"], "render_fps": 60}
    def __init__(
        self,
        num_players: int = 1,
        num_pellets: int = 200,
        pellet_mass: float = 1.0,
        player_mass_base: float = 10.0,
        player_mass_decay: float = 0.99,
        player_speed_inv_pow: float = -0.44,
        player_speed_scale: float = 10.0,
        world_size: int = 800,
        sqrt_mass_to_radius: float = 1.0,
        render_mode: str = None,
    ):

        self.num_players = num_players
        self.num_pellets = num_pellets
        self.pellet_mass = pellet_mass
        self.pellet_radius = np.sqrt(self.pellet_mass) * sqrt_mass_to_radius
        self.player_mass_base = player_mass_base
        self.player_mass_decay = player_mass_decay
        self.player_speed_inv_pow = player_speed_inv_pow
        self.player_speed_scale = player_speed_scale
        self.world_size = world_size
        self.sqrt_mass_to_radius = sqrt_mass_to_radius

        # noop, right, up, left, down for each player
        self.action_space = MultiDiscrete([5] * num_players)
        self._action_to_direction = np.array(
            [
                [0, 0],
                [1, 0],
                [0, 1],
                [-1, 0],
                [0, -1],
            ]
        )

        # players and pellet positions
        self.observation_space = Dict(
            {
                "player_masses": Box(
                    low=0, high=np.inf, shape=(num_players,), dtype=np.float64
                ),
                "player_is_alive": MultiBinary(num_players),
                "player_locations": Box(
                    low=0, high=world_size, shape=(num_players, 2), dtype=np.float64
                ),
                "pellet_locations": Box(
                    low=0, high=world_size, shape=(num_pellets, 2), dtype=np.float64
                ),
            }
        )

        # rendering setup
        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode
        self.window = None
        self.clock = None
        self.window_size = world_size

    def reset(self, seed=None, options=None):
        super().reset(seed=seed, options=options)

        self._player_masses = np.full(
            self.num_players, self.player_mass_base, dtype=np.float64
        )
        self._player_is_alive = np.full(self.num_players, True, dtype=np.bool)
        self._player_locations = (
            self.np_random.random((self.num_players, 2)) * self.world_size
        )
        self._pellet_locations = (
            self.np_random.random((self.num_pellets, 2)) * self.world_size
        )

        self._update_player_distances()
        self._update_player_radii()

        observation = self._get_observation()
        info = self._get_info()

        if self.render_mode == "human":
            self.render()

        return observation, info

    def step(self, actions):
        self._update_player_locations(actions)
        self._update_player_distances()
        self._update_player_radii()

        prev_masses = self._player_masses.copy()
        players_eaten, pellets_eaten = self._update_player_masses()
        self._update_player_is_alive(players_eaten)
        self._update_pellet_locations(pellets_eaten)

        observation = self._get_observation()
        reward = self._get_reward(prev_masses)
        terminated = self._get_terminated()
        truncated = self._get_truncated()
        info = self._get_info()

        if self.render_mode == "human":
            self.render()

        return observation, reward, terminated, truncated, info

    def render(self):
        if self.window is None and self.render_mode == "human":
            pygame.init()
            pygame.display.init()
            self.window = pygame.display.set_mode(
                (self.window_size, self.window_size)
            )
        if self.clock is None and self.render_mode == "human":
            self.clock = pygame.time.Clock()
        canvas = pygame.Surface((self.window_size, self.window_size))
        canvas.fill((255, 255, 255))
        
        for i in range(self.num_players):
            x = self._player_locations[i][0]
            y = self._player_locations[i][1]
            radius = self._player_radii[i]
            pygame.draw.circle(
                canvas,
                (0, 0, 255),
                (x, self.world_size - y - 1),  # correct for inverted y
                radius
            )

        for i in range(self.num_pellets):
            x = self._pellet_locations[i][0]
            y = self._pellet_locations[i][1]
            radius = self.pellet_radius
            pygame.draw.circle(
                canvas,
                (255, 0, 0),
                (x, self.world_size - y - 1),  # correct for inverted y
                radius
            )

        if self.render_mode == "human":
            # The following line copies our drawings from `canvas` to the visible window
            self.window.blit(canvas, canvas.get_rect())
            pygame.event.pump()
            pygame.display.update()

            # We need to ensure that human-rendering occurs at the predefined framerate.
            # The following line will automatically add a delay to keep the framerate stable.
            self.clock.tick(self.metadata["render_fps"])

    def close(self):
        if self.window is not None:
            pygame.display.quit()
            pygame.quit()

    def _update_player_locations(self, actions):
        self._player_locations[self._player_is_alive] = np.clip(
            self._player_locations[self._player_is_alive]
            + self._action_to_direction[actions[self._player_is_alive]]
            * np.power(self._player_masses[self._player_is_alive], self.player_speed_inv_pow)[:, np.newaxis]
            * self.player_speed_scale,
            0, self.world_size,
        )

    def _update_player_radii(self):
        self._player_radii = np.sqrt(self._player_masses) * self.sqrt_mass_to_radius

    def _update_player_distances(self):
        self._player_to_player_distances = distance_matrix(
            self._player_locations, self._player_locations
        )
        self._player_to_pellet_distances = distance_matrix(
            self._player_locations, self._pellet_locations
        )

    def _update_player_masses(self):
        # add mass for eaten pellets and players
        player_eats_player = (
            (self._player_to_player_distances < self._player_radii[:, np.newaxis])
            & (self._player_radii[:, np.newaxis] > self._player_radii[np.newaxis, :])
        ).astype(np.float64)
        player_eats_pellet = (
            (self._player_to_pellet_distances < self._player_radii[:, np.newaxis] + self.pellet_radius)
            & (self._player_radii[:, np.newaxis] > self.pellet_radius)
        ).astype(np.float64)

        players_eaten = np.nonzero(np.any(player_eats_player, axis=0))[0]
        pellets_eaten = np.nonzero(np.any(player_eats_pellet, axis=0))[0]

        # divide mass evenly among players that ate the same player or pellet
        player_eats_player[:, players_eaten] /= np.sum(
            player_eats_player[:, players_eaten], axis=0, keepdims=True
        )
        player_eats_pellet[:, pellets_eaten] /= np.sum(
            player_eats_pellet[:, pellets_eaten], axis=0, keepdims=True
        )
        self._player_masses += np.sum(player_eats_pellet * self.pellet_mass, axis=1)
        self._player_masses += np.sum(player_eats_player * self._player_masses, axis=1)

        # decay player mass
        self._player_masses[self._player_is_alive] = np.maximum(
            self._player_masses[self._player_is_alive] * self.player_mass_decay,
            self.player_mass_base)

        # set eaten players to 0 mass
        self._player_masses[players_eaten] = 0

        return players_eaten, pellets_eaten
    
    def _update_player_is_alive(self, players_eaten):
        self._player_is_alive[players_eaten] = False

    def _update_pellet_locations(self, pellets_eaten):
        # respawn eaten pellets in random unoccupied locations
        for i in pellets_eaten:
            while np.any(
                np.linalg.norm(
                    self._pellet_locations[i] - self._player_locations, axis=-1
                )
                < self._player_radii
            ):
                self._pellet_locations[i] = self.np_random.random(2) * self.world_size

    def _get_observation(self):
        return {
            "player_masses": self._player_masses,
            "player_is_alive": self._player_is_alive,
            "player_locations": self._player_locations,
            "pellet_locations": self._pellet_locations,
        }

    def _get_reward(self, prev_masses):
        return self._player_masses - prev_masses

    def _get_terminated(self):
        return np.count_nonzero(self._player_masses) <= 1

    def _get_truncated(self):
        return False

    def _get_info(self):
        return {
            "player_radii": self._player_radii,
            "player_to_player_distances": self._player_to_player_distances,
            "player_to_pellet_distances": self._player_to_pellet_distances,
        }
