from collections import Counter

class Item_():
    def __init__(self, ply, item_list):
        self.player = ply
        self.item = item_list

    def HP_Potion_S(player):
        print("HP_S 포션을 사용하였다! +50\n")
        player.hp = min(player.maxhp, player.hp + 50)

    def HP_Potion_M(player):
        print("HP_M 포션을 사용하였다! +100\n")
        player.hp = min(player.maxhp, player.hp + 100)

    def HP_Potion_L(player):
        print("HP_L 포션을 사용하였다! +150\n")
        player.hp = min(player.maxhp, player.hp + 150)

    def MP_Potion_S(player):
        print("MP_S 포션을 사용하였다! +20\n")
        player.mp = min(player.maxmp, player.mp + 20)

    def MP_Potion_M(player):
        print("MP_M 포션을 사용하였다! +40\n")
        player.mp = min(player.maxmp, player.mp + 40)

    def MP_Potion_L(player):
        print("MP_L 포션을 사용하였다! +60\n")
        player.mp = min(player.maxmp, player.mp + 60)

    def show_item(self):
        if not self.item:
            print("보유 아이템이 없습니다\n")
            return
        print("아이템 목록:")
        item_count = Counter(self.item)
        for idx, (name, count) in enumerate(item_count.items()):
            print(f"{idx} - {name} x{count}")

    def use_item(self, item):
        item_effects = {
            "HP_S_potion": Item_.HP_Potion_S,
            "HP_M_potion": Item_.HP_Potion_M,
            "HP_L_potion": Item_.HP_Potion_L,
            "MP_S_potion": Item_.MP_Potion_S,
            "MP_M_potion": Item_.MP_Potion_M,
            "MP_L_potion": Item_.MP_Potion_L,
        }
        if item in item_effects:
            item_effects[item](self.player)
            self.item.remove(item)
        else:
            print("잘못된 입력입니다.\n")