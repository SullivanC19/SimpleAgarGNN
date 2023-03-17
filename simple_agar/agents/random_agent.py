from simple_agar.agents.base_agent import BaseAgent

class RandomAgent(BaseAgent):
    def __init__(self, action_space):
        super().__init__()
        self.action_space = action_space

    def act(self, observation, info):
        return self.action_space.sample()