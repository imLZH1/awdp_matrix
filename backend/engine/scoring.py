import math

class ScoringEngine:
    @staticmethod
    def calculate_dynamic_score(a: float, s: int, x: int) -> float:
        """
        基于二次函数的动态积分公式
        公式: (x - 1)^2 * [(50 - a) / s^2] + a
        
        参数:
        - a: 赛题初始分数 (如 500)
        - s: 参赛队伍总数
        - x: 解题先后排名，或当前解出该题的总队伍数
        """
        if x <= 1:
            return float(a)
            
        # 防止除 0 错误
        if s <= 0:
            s = 1
            
        # 根据需求：[(50 - a) / s^2]
        coefficient = (50.0 - a) / math.pow(s, 2)
        score = math.pow(x - 1, 2) * coefficient + a
        return round(score, 2)

    @staticmethod
    def calculate_bonus_score(a: float, rank: int) -> float:
        """
        前 20 名加成公式
        第 1 名: 5%
        第 2 名: 4.9%
        ...
        第 20 名: 3.1%
        第 20 名之后: 0%
        """
        if rank <= 0 or rank > 20:
            return 0.0
            
        # 第 1 名是 0.05, 每降一名减少 0.001
        percentage = round(0.05 - (rank - 1) * 0.001, 3)
        return round(a * percentage, 2)

    @staticmethod
    def calculate_blood_bonus(s_break: float, blood_rank: int) -> float:
        """
        兼容旧版 CTF 的一二三血额外奖励积分
        一血奖励：S_break 的 3%
        二血奖励：S_break 的 2%
        三血奖励：S_break 的 1%
        """
        if blood_rank == 1:
            return round(s_break * 0.03, 2)
        elif blood_rank == 2:
            return round(s_break * 0.02, 2)
        elif blood_rank == 3:
            return round(s_break * 0.01, 2)
        return 0.0

    @staticmethod
    def calculate_awdp_attack_score(s_break: float, victim_count: int, total_active_teams: int) -> float:
        """
        AWDP 攻击得分公式（每轮）
        将该题当前的动态分值作为基准
        每次成功攻击获得该基准分的一个固定比例，这里可以暂时设定为该分值的 10%
        """
        # 每轮该题目的攻击总价值（池）
        round_pool = s_break * 0.1 
        
        # 被攻击者最多扣除池子里的分数
        victim_loss = round(round_pool, 2)
        
        # 攻击者平分这些分数
        attacker_gain = round(round_pool / max(1, victim_count), 2)
        
        return attacker_gain, victim_loss
        
    @staticmethod
    def calculate_awdp_defense_score(v_round: float, sla: int, p_down: float) -> float:
        """
        AWDP 防御得分公式（每轮）
        S_defense = (V_round * SLA - P_down) - Loss_attack
        这里只计算前一半 (V_round * SLA - P_down)，Loss_attack 在主逻辑中单独扣除
        V_round: 每轮次的基础防御分 (例如基础分的 5%)
        SLA: 可用性系数（0 或 1）
        P_down: 宕机惩罚
        """
        return round(v_round * sla - p_down, 2)
